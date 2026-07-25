"""Read-side queries that feed the frontend (Live Sniper + Market Intelligence).

Routing table-per-type: le opportunità vivono in ``live_opportunities_auto``
(categoria 'automobile') o ``live_opportunities_tech`` (smartphone/tech), sono
chiavate su ``target_id`` (→ ``target_models.query`` = nome modello) e i cali di
prezzo sono storicizzati in ``price_history`` (listing_id = id opportunità).

Oltre al feed grezzo, questo modulo produce l'intelligence azionabile:
Deal Score + assistente trattativa (scoring.py), valutazione km-aware per le
auto (regressione prezzo~km per target), storico venditore, time-to-sale per
modello (dai ``venduto_rimosso`` del Garbage Collector) e prezzi di
rivendita suggeriti dalla distribuzione dei prezzi attivi.
"""

from __future__ import annotations

import logging
import re
import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from backend.core.database import Client

from backend.core.database import get_db
from backend.services.scoring import evaluate_opportunity
from backend.services.valuation import evaluate_value
from backend.services.variants import is_healthy

logger = logging.getLogger(__name__)

_LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")

_ACTIVE_STATUSES = ("nuovo", "visto")
_SOLD_STATUSES = ("venduto_rimosso", "scaduto")

# I target_model salvano la categoria come 'automobile' / 'smartphone'; il
# frontend può passare anche l'alias 'auto'.
_AUTO_CATEGORIES = frozenset({"automobile", "auto"})


def _opportunities_table(category: str) -> str:
    """Routing: 'automobile' → _auto, tutto il resto (smartphone/tech) → _tech."""
    return (
        "live_opportunities_auto"
        if category in _AUTO_CATEGORIES
        else "live_opportunities_tech"
    )


def _target_category(category: str) -> str:
    """Normalizza verso il valore usato in target_models/products."""
    return "automobile" if category in _AUTO_CATEGORIES else "smartphone"


def _to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _title_from_url(url: str | None) -> str | None:
    """Best-effort readable title from a Subito listing slug."""
    if not url:
        return None
    path = urlparse(url).path.rsplit("/", 1)[-1]
    slug = _LISTING_ID_RE.sub("", path).removesuffix(".htm")
    if not slug:
        return None
    return slug.replace("-", " ").strip().title() or None


def _products_for_category(db: Client, category: str) -> dict[str, str]:
    rows = (
        db.table("products")
        .select("id, model")
        .eq("category", category)
        .execute()
    )
    return {row["id"]: row["model"] for row in rows.data or []}


def _targets_for_category(db: Client, category: str) -> dict[str, str]:
    """target_id → query (nome modello) per la categoria richiesta."""
    rows = (
        db.table("target_models")
        .select("id, query")
        .eq("category", category)
        .execute()
    )
    return {row["id"]: row["query"] for row in rows.data or []}


def _market_avgs(
    db: Client, category: str
) -> tuple[dict[str, float], dict[str, float]]:
    """Ultime medie di mercato (market_trends): (per target_id, per modello).

    L'isolamento vero è per target_id (una BMW 318d Gen1 non inquina la Gen3):
    ``by_target`` è la mappa preferita. ``by_model`` (per nome modello, via
    product_id→products) resta come fallback per gli snapshot legacy privi di
    target_id. In entrambe teniamo lo snapshot più recente.
    """
    products = _products_for_category(db, category)  # id → model
    if not products:
        return {}, {}

    trends = (
        db.table("market_trends")
        .select("target_id, product_id, trend_date, avg_price")
        .in_("product_id", list(products))
        .order("trend_date", desc=True)
        .execute()
    )
    by_target: dict[str, float] = {}
    by_model: dict[str, float] = {}
    for row in trends.data or []:
        avg = _to_float(row.get("avg_price"))
        if avg is None:
            continue
        # order desc → la prima occorrenza per chiave è la più recente.
        target_id = row.get("target_id")
        if target_id and target_id not in by_target:
            by_target[target_id] = avg
        model = products.get(row["product_id"])
        if model and model not in by_model:
            by_model[model] = avg
    return by_target, by_model


def _latest_price_history(
    db: Client, listing_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """listing_id → ultimo record di calo (old_price/new_price/changed_at)."""
    if not listing_ids:
        return {}
    rows = (
        db.table("price_history")
        .select("listing_id, old_price, new_price, changed_at")
        .in_("listing_id", listing_ids)
        .order("changed_at", desc=True)
        .execute()
    )
    latest: dict[str, dict[str, Any]] = {}
    for row in rows.data or []:
        # order desc → prima occorrenza per listing_id è la più recente.
        latest.setdefault(row["listing_id"], row)
    return latest


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seller_active_counts(
    db: Client, table: str, rows: list[dict[str, Any]]
) -> dict[str, int]:
    """seller_id → n. annunci ATTIVI in `table` (storico venditore, A3).

    Un "privato" con 6 annunci attivi si tratta come un commerciante.
    """
    seller_ids = list({r.get("seller_id") for r in rows if r.get("seller_id")})
    if not seller_ids:
        return {}
    try:
        found = (
            db.table(table)
            .select("seller_id")
            .in_("seller_id", seller_ids)
            .in_("status", list(_ACTIVE_STATUSES))
            .execute()
        )
    except Exception:
        return {}
    counts: dict[str, int] = {}
    for row in found.data or []:
        sid = row.get("seller_id")
        if sid:
            counts[sid] = counts.get(sid, 0) + 1
    return counts


_KM_MODEL_MIN_SAMPLES = 8


def _km_price_models(
    db: Client, table: str, target_ids: list[str]
) -> dict[str, tuple[float, float, int]]:
    """Regressione lineare prezzo~km per target (A1, solo auto).

    target_id → (slope, intercept, n). Il modello è accettato solo con ≥ 8
    campioni e pendenza negativa (il prezzo DEVE scendere coi km: una
    pendenza positiva indica dati sporchi, meglio nessuna stima).
    """
    models: dict[str, tuple[float, float, int]] = {}
    for target_id in target_ids:
        try:
            rows = (
                db.table(table)
                .select("km, asking_price")
                .eq("target_id", target_id)
                .in_("status", list(_ACTIVE_STATUSES))
                .not_.is_("km", "null")
                .limit(500)
                .execute()
            ).data or []
        except Exception:
            continue
        points = [
            (float(r["km"]), float(r["asking_price"]))
            for r in rows
            if r.get("km") and r.get("asking_price")
            and float(r["asking_price"]) > 0
        ]
        if len(points) < _KM_MODEL_MIN_SAMPLES:
            continue
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        try:
            slope, intercept = statistics.linear_regression(xs, ys)
        except statistics.StatisticsError:
            continue
        if slope >= 0:
            continue
        models[target_id] = (slope, intercept, len(points))
    return models


def _shape_opportunity(
    row: dict[str, Any],
    model: str | None,
    market_avg: float | None,
    price_drop: dict[str, Any] | None,
) -> dict[str, Any]:
    asking = _to_float(row.get("asking_price"))
    original = _to_float(row.get("original_price"))

    margin_eur: float | None = None
    margin_pct: float | None = None
    if market_avg is not None and asking is not None:
        margin_eur = round(market_avg - asking, 2)
        if asking > 0:
            margin_pct = round(margin_eur / asking * 100, 1)

    # Price Drop Alert: preferisci lo storico esplicito, altrimenti deducilo da
    # original_price (settato dallo Sniper quando il prezzo è sceso).
    drop: dict[str, Any] | None = None
    if price_drop is not None:
        drop = {
            "oldPrice": _to_float(price_drop.get("old_price")),
            "newPrice": _to_float(price_drop.get("new_price")),
            "changedAt": price_drop.get("changed_at"),
        }
    elif original is not None and asking is not None and original > asking:
        drop = {"oldPrice": original, "newPrice": asking, "changedAt": None}

    found = _parse_ts(row.get("found_at"))
    days_online = (
        max(0, (datetime.now(timezone.utc) - found).days) if found else None
    )

    return {
        "id": row["id"],
        "title": row.get("title") or _title_from_url(row.get("listing_url")) or model,
        "location": row.get("location"),
        "askingPrice": asking,
        "originalPrice": original,
        "marketAvg": market_avg,
        "marginEur": margin_eur,
        "marginPct": margin_pct,
        "priceDrop": drop,
        "description": row.get("description"),
        "images": row.get("image_urls") or [],
        "foundAt": row.get("found_at"),
        "daysOnline": days_online,
        "source": "Subito",
        "status": row.get("status"),
        "url": row.get("listing_url"),
        # Segnale NLP + venditore (per score/trattativa e UI).
        "sellerType": row.get("seller_type"),
        "defects": row.get("defects_noted") or [],
        "urgencyFlags": row.get("urgency_flags") or [],
        "features": row.get("features") or [],
        # Verticale-specifici (None dove non pertinenti).
        "year": row.get("year"),
        "km": row.get("km"),
        "transmission": row.get("transmission"),
        "fuel": row.get("fuel"),
        "storageGb": row.get("storage_gb"),
        "batteryPct": row.get("battery_pct"),
        # Variante canonica (scrematura) + fascia di condizione + colore.
        "variantKey": row.get("variant_key"),
        "conditionTier": row.get("condition_tier"),
        "color": row.get("color"),
    }


def _iqr_clean(values: list[float]) -> list[float]:
    """Rimuove gli outlier con la regola 1.5*IQR (serve >= 4 campioni)."""
    vals = sorted(v for v in values if v and v > 0)
    if len(vals) < 4:
        return vals
    q1, _, q3 = statistics.quantiles(vals, n=4)
    iqr = q3 - q1
    if iqr <= 0:
        return vals
    low, high = q1 - 1.5 * iqr, q3 + 1.5 * iqr
    return [v for v in vals if low <= v <= high]


def _variant_price_pools(db: Client, table: str) -> dict[str, list[float]]:
    """Pool di prezzi SANI per VARIANTE canonica — la base della valutazione.

    Dai listing ATTIVI e SANI (esclude rotti/incidentati), raggruppati per
    ``variant_key`` e ripuliti con IQR. La lista (non solo la media) serve alla
    Fase 2: mediana robusta come valore equo e percentili per la posizione.
    """
    try:
        rows = (
            db.table(table)
            .select("variant_key, asking_price, condition_tier")
            .in_("status", list(_ACTIVE_STATUSES))
            .execute()
            .data
            or []
        )
    except Exception:
        return {}

    buckets: dict[str, list[float]] = {}
    for row in rows:
        vk = row.get("variant_key")
        price = _to_float(row.get("asking_price"))
        if not vk or vk == "auto" or price is None or price <= 0:
            # "auto" = catch-all di righe storiche senza target: mix inutile.
            continue
        if not is_healthy(row.get("condition_tier") or "buono"):
            continue
        buckets.setdefault(vk, []).append(price)

    pools: dict[str, list[float]] = {}
    for vk, prices in buckets.items():
        cleaned = _iqr_clean(prices)
        if len(cleaned) >= 3:
            pools[vk] = cleaned
    return pools


def _model_key(variant_key: str | None) -> str | None:
    """Chiave modello = variante senza il suffisso memoria (iphone-13-pro-max-256
    → iphone-13-pro-max). Serve per filtrare per modello senza ambiguità."""
    if not variant_key or variant_key == "auto":
        return None
    return variant_key.rsplit("-", 1)[0]


def _model_label(model_key: str) -> str:
    """iphone-13-pro-max → 'iPhone 13 Pro Max'; iphone-16e → 'iPhone 16e'."""
    parts = model_key.split("-")
    if parts and parts[0] == "iphone":
        rest = " ".join(p if p[:1].isdigit() else p.capitalize() for p in parts[1:])
        return f"iPhone {rest}".strip()
    return model_key.replace("-", " ").title()


def _opportunity_facets(db: Client, table: str) -> dict[str, Any]:
    """Valori disponibili per i filtri (modello/memoria/colore/condizione) con
    conteggi, dai listing attivi — popola i menu a tendina della dashboard."""
    rows = (
        db.table(table)
        .select("variant_key, storage_gb, color, condition_tier")
        .in_("status", list(_ACTIVE_STATUSES))
        .execute()
        .data
        or []
    )
    models: Counter = Counter()
    storages: Counter = Counter()
    colors: Counter = Counter()
    conditions: Counter = Counter()
    for r in rows:
        mk = _model_key(r.get("variant_key"))
        if mk:
            models[mk] += 1
        if r.get("storage_gb"):
            storages[r["storage_gb"]] += 1
        if r.get("color"):
            colors[r["color"]] += 1
        if r.get("condition_tier"):
            conditions[r["condition_tier"]] += 1
    return {
        "models": [
            {"key": k, "label": _model_label(k), "count": c}
            for k, c in sorted(models.items(), key=lambda x: -x[1])
        ],
        "storages": [{"value": s, "count": c} for s, c in sorted(storages.items())],
        "colors": [
            {"value": k, "count": c}
            for k, c in sorted(colors.items(), key=lambda x: -x[1])
        ],
        "conditions": [
            {"value": k, "count": c}
            for k, c in sorted(conditions.items(), key=lambda x: -x[1])
        ],
    }


def _enrich_opportunity(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Arricchisce una riga con margine, variante, valutazione, Deal Score e
    assistente di trattativa (il cuore BI, per singola opportunità)."""
    target_id = row.get("target_id")
    model = ctx["targets"].get(target_id)
    variant_key = row.get("variant_key")
    pool = ctx["variant_pools"].get(variant_key) if variant_key else None
    market_avg = round(statistics.fmean(pool), 2) if pool and len(pool) >= 3 else None
    if market_avg is None:
        market_avg = ctx["avg_by_target"].get(target_id)
    if market_avg is None and model:
        market_avg = ctx["avg_by_model"].get(model)

    shaped = _shape_opportunity(row, model, market_avg, ctx["price_history"].get(row["id"]))

    seller_id = row.get("seller_id")
    shaped["sellerActiveCount"] = (
        ctx["seller_counts"].get(seller_id) if seller_id else None
    )

    shaped["expectedPrice"] = None
    shaped["marginVsExpected"] = None
    km_model = ctx["km_models"].get(target_id) if target_id else None
    if km_model and row.get("km") and shaped["askingPrice"]:
        slope, intercept, _n = km_model
        expected = intercept + slope * float(row["km"])
        if expected > 0:
            shaped["expectedPrice"] = round(expected, 2)
            shaped["marginVsExpected"] = round(expected - shaped["askingPrice"], 2)

    valuation = evaluate_value(
        category=ctx["target_cat"],
        asking=shaped["askingPrice"],
        condition_tier=row.get("condition_tier"),
        variant_prices=pool or [],
        km=row.get("km"),
        km_model=km_model,
        has_images=bool(row.get("image_urls")),
    )
    shaped.update(valuation)

    score_margin = (
        valuation["marginVsFairPct"]
        if valuation["marginVsFairPct"] is not None
        else shaped["marginPct"]
    )
    shaped.update(
        evaluate_opportunity(
            category=ctx["target_cat"],
            title=shaped["title"],
            asking=shaped["askingPrice"],
            market_avg=valuation["fairValue"] or market_avg,
            margin_pct=score_margin,
            found_at=row.get("found_at"),
            seller_type=row.get("seller_type"),
            defects=shaped["defects"],
            urgency=shaped["urgencyFlags"],
            features=shaped["features"],
            battery_pct=shaped["batteryPct"],
            has_price_drop=shaped["priceDrop"] is not None,
        )
    )
    if valuation["dealClass"] == "sospetto":
        shaped["score"] = 0
        shaped["scoreBreakdown"] = [
            {"label": "⚠️ Prezzo sospetto (possibile truffa/errore)", "points": 0}
        ]
    return shaped


def list_opportunities(
    category: str,
    *,
    sort: str = "score",
    model: str | None = None,
    storage: int | None = None,
    color: str | None = None,
    condition: str | None = None,
    deal_class: str | None = None,
    min_margin: float | None = None,
    q: str | None = None,
    limit: int = 30,
    offset: int = 0,
    client: Client | None = None,
) -> dict[str, Any]:
    """Feed opportunità: TUTTE le attive, ordinate (default Deal Score), con
    filtri (modello/memoria/colore/condizione/classe/margine) e paginazione.

    Ritorna {items, total, facets}. I filtri strutturali non ambigui
    (memoria/colore/condizione) sono applicati a livello DB; modello, classe
    affare, margine e ricerca testuale in Python (dipendono da campi derivati).
    """
    db = client or get_db()
    table = _opportunities_table(category)
    target_cat = _target_category(category)

    facets = _opportunity_facets(db, table)

    query = db.table(table).select("*").in_("status", list(_ACTIVE_STATUSES))
    if storage is not None:
        query = query.eq("storage_gb", storage)
    if color:
        query = query.eq("color", color)
    if condition:
        query = query.eq("condition_tier", condition)
    rows = query.execute().data or []
    if not rows:
        return {"items": [], "total": 0, "facets": facets}

    variant_pools = _variant_price_pools(db, table)
    ctx: dict[str, Any] = {
        "target_cat": target_cat,
        "targets": _targets_for_category(db, target_cat),
        "variant_pools": variant_pools,
        "price_history": _latest_price_history(db, [r["id"] for r in rows]),
        "seller_counts": _seller_active_counts(db, table, rows),
        "km_models": {},
    }
    avg_by_target, avg_by_model = _market_avgs(db, target_cat)
    ctx["avg_by_target"] = avg_by_target
    ctx["avg_by_model"] = avg_by_model
    if target_cat == "automobile":
        auto_targets = list(
            {r["target_id"] for r in rows if r.get("target_id") and r.get("km")}
        )
        ctx["km_models"] = _km_price_models(db, table, auto_targets)

    items = [_enrich_opportunity(r, ctx) for r in rows]

    # Filtri applicati in Python (campi derivati / ambigui via DB).
    if model:
        items = [it for it in items if _model_key(it.get("variantKey")) == model]
    if deal_class:
        items = [it for it in items if it.get("dealClass") == deal_class]
    if min_margin is not None:
        items = [
            it for it in items
            if it.get("marginPct") is not None and it["marginPct"] >= min_margin
        ]
    if q:
        ql = q.strip().lower()
        items = [
            it for it in items
            if ql in (it.get("title") or "").lower()
            or ql in (it.get("location") or "").lower()
        ]

    if sort == "recent":
        items.sort(key=lambda it: it.get("foundAt") or "", reverse=True)
    elif sort == "margin":
        items.sort(
            key=lambda it: it["marginPct"] if it.get("marginPct") is not None else -1e9,
            reverse=True,
        )
    else:  # score (default)
        items.sort(key=lambda it: it.get("score") or 0, reverse=True)

    total = len(items)
    return {"items": items[offset : offset + limit], "total": total, "facets": facets}


def _price_bands(points: list[tuple[float, float]]) -> list[dict[str, Any]]:
    """Divide i venduti in fasce di prezzo (economico/medio/alto) e calcola i
    giorni medi di vendita per fascia → 'a quale prezzo si vende in quanti giorni'.
    """
    if len(points) < 6:
        return []
    ordered = sorted(points, key=lambda x: x[0])
    n = len(ordered)
    thirds = [ordered[: n // 3], ordered[n // 3 : 2 * n // 3], ordered[2 * n // 3 :]]
    bands: list[dict[str, Any]] = []
    for label, grp in zip(("economico", "medio", "alto"), thirds):
        if not grp:
            continue
        prices = [p for p, _ in grp]
        days = [d for _, d in grp]
        bands.append(
            {
                "band": label,
                "priceFrom": round(min(prices)),
                "priceTo": round(max(prices)),
                "avgDays": round(statistics.fmean(days), 1),
                "count": len(grp),
            }
        )
    return bands


def _sold_stats(
    db: Client, table: str, targets: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], float | None]:
    """Statistiche dai VENDUTI (annunci spariti) — il segnale di vendita reale.

    Il Garbage Collector marca 'venduto_rimosso' (annuncio sparito da Subito =
    proxy di venduto) conservando l'ultimo ``asking_price`` e aggiornando
    ``updated_at``. Da qui, per modello: giorni medi di vendita (found→sparizione),
    **prezzo di vendita reale** (mediana/max dei venduti, NON dei listati) e le
    fasce prezzo→giorni. Solo listing sani. Ritorna (per_modello, mediana giorni).
    """
    try:
        rows = (
            db.table(table)
            .select("target_id, asking_price, found_at, updated_at, condition_tier")
            .in_("status", list(_SOLD_STATUSES))
            .order("updated_at", desc=True)
            .limit(5000)
            .execute()
        ).data or []
    except Exception:
        return {}, None

    by_model: dict[str, list[tuple[float, float]]] = {}
    all_days: list[float] = []
    for row in rows:
        if not is_healthy(row.get("condition_tier") or "buono"):
            continue
        model = targets.get(row.get("target_id"))
        price = _to_float(row.get("asking_price"))
        found = _parse_ts(row.get("found_at"))
        removed = _parse_ts(row.get("updated_at"))
        if not model or price is None or price <= 0 or not found or not removed:
            continue
        days = (removed - found).total_seconds() / 86400
        if not (0 <= days <= 365):
            continue
        by_model.setdefault(model, []).append((price, days))
        all_days.append(days)

    per_model: dict[str, dict[str, Any]] = {}
    for model, pts in by_model.items():
        if len(pts) < 3:
            continue
        prices = [p for p, _ in pts]
        days = [d for _, d in pts]
        per_model[model] = {
            "avgDaysToSell": round(statistics.fmean(days), 1),
            "sampleSold": len(pts),
            "soldMedian": round(statistics.median(prices)),
            "soldMax": round(max(prices)),
            "priceBands": _price_bands(pts),
        }
    overall = round(statistics.median(all_days), 1) if all_days else None
    return per_model, overall


def _resale_suggestions(
    db: Client, table: str, targets: dict[str, str]
) -> dict[str, dict[str, float]]:
    """Prezzo di rivendita suggerito (C7) dalla distribuzione dei prezzi attivi.

    Per modello: 'fastSalePrice' = 25° percentile (ti posizioni tra i più
    economici → vendita rapida), 'maxSalePrice' = mediana (prezzo pieno).
    """
    try:
        rows = (
            db.table(table)
            .select("target_id, asking_price")
            .in_("status", list(_ACTIVE_STATUSES))
            .limit(2000)
            .execute()
        ).data or []
    except Exception:
        return {}

    prices_by_model: dict[str, list[float]] = {}
    for row in rows:
        model = targets.get(row.get("target_id"))
        price = _to_float(row.get("asking_price"))
        if model and price and price > 0:
            prices_by_model.setdefault(model, []).append(price)

    result: dict[str, dict[str, float]] = {}
    for model, prices in prices_by_model.items():
        if len(prices) < 4:
            continue
        q1, q2, _q3 = statistics.quantiles(sorted(prices), n=4)
        result[model] = {
            "fastSalePrice": round(q1, 0),
            "maxSalePrice": round(q2, 0),
        }
    return result


def get_market_intelligence(
    category: str,
    client: Client | None = None,
) -> dict[str, Any]:
    """KPIs, price trend series and per-model stats for a vertical."""
    db = client or get_db()
    target_cat = _target_category(category)
    products = _products_for_category(db, target_cat)

    empty = {
        "activeListings": 0,
        "avgMarketPrice": None,
        "outliersFiltered": None,
        "avgDaysToSell": None,
        "trend": [],
        "trendProduct": None,
        "models": [],
    }

    # Annunci attivi: conteggio reale sulla tabella per-tipo (chiavata su target).
    table = _opportunities_table(category)
    try:
        active_listings = (
            db.table(table).select("id", count="exact").limit(1).execute().count or 0
        )
    except Exception:
        active_listings = 0

    # Statistiche dai VENDUTI (prezzo reale + giorni) e prezzi dei listati attivi.
    targets = _targets_for_category(db, target_cat)
    sold_by_model, overall_tts = _sold_stats(db, table, targets)
    resale_by_model = _resale_suggestions(db, table, targets)

    if not products:
        return {
            **empty,
            "activeListings": active_listings,
            "avgDaysToSell": overall_tts,
        }

    product_ids = list(products)

    trends = (
        db.table("market_trends")
        .select("product_id, trend_date, avg_price, volume")
        .in_("product_id", product_ids)
        .order("trend_date", desc=False)
        .execute()
    )
    trend_rows = trends.data or []

    # Group trend rows by product to build per-model stats and the chart series.
    by_product: dict[str, list[dict[str, Any]]] = {}
    for row in trend_rows:
        by_product.setdefault(row["product_id"], []).append(row)

    models: list[dict[str, Any]] = []
    latest_avgs: list[float] = []
    for product_id, rows in by_product.items():
        rows_sorted = sorted(rows, key=lambda r: r["trend_date"])
        latest = rows_sorted[-1]
        latest_avg = _to_float(latest.get("avg_price"))
        if latest_avg is not None:
            latest_avgs.append(latest_avg)
        change_pct: float | None = None
        if len(rows_sorted) >= 2 and latest_avg:
            prev_avg = _to_float(rows_sorted[0].get("avg_price"))
            if prev_avg:
                change_pct = round((latest_avg - prev_avg) / prev_avg * 100, 1)
        name = products.get(product_id, "—")
        sold = sold_by_model.get(name) or {}
        resale = resale_by_model.get(name) or {}
        models.append(
            {
                "name": name,
                "avg": latest_avg,
                "sample": latest.get("volume"),
                "changePct": change_pct,
                # Liquidità: giorni medi di vendita (dai venduti).
                "avgDaysToSell": sold.get("avgDaysToSell"),
                "sampleSold": sold.get("sampleSold"),
                # Prezzo di vendita REALE (dai venduti, non dai listati) + fasce.
                "soldMedian": sold.get("soldMedian"),
                "soldMax": sold.get("soldMax"),
                "priceBands": sold.get("priceBands") or [],
                # Prezzi dei LISTATI attivi (fallback / confronto).
                "fastSalePrice": resale.get("fastSalePrice"),
                "maxSalePrice": resale.get("maxSalePrice"),
                # Serie storica completa: curva di deprezzamento.
                "series": [
                    {"date": r["trend_date"], "price": _to_float(r.get("avg_price"))}
                    for r in rows_sorted
                    if _to_float(r.get("avg_price")) is not None
                ],
            }
        )

    models.sort(key=lambda m: (m["sample"] or 0), reverse=True)
    avg_market_price = (
        round(sum(latest_avgs) / len(latest_avgs), 2) if latest_avgs else None
    )

    # Chart: the trend series of the most-sampled product in this vertical.
    trend_series: list[dict[str, Any]] = []
    trend_product: str | None = None
    if models:
        top_name = models[0]["name"]
        top_id = next((pid for pid, m in products.items() if m == top_name), None)
        if top_id and top_id in by_product:
            trend_product = top_name
            for row in sorted(by_product[top_id], key=lambda r: r["trend_date"]):
                price = _to_float(row.get("avg_price"))
                if price is not None:
                    trend_series.append({"date": row["trend_date"], "price": price})

    return {
        "activeListings": active_listings,
        "avgMarketPrice": avg_market_price,
        "outliersFiltered": None,
        "avgDaysToSell": overall_tts,
        "trend": trend_series,
        "trendProduct": trend_product,
        "models": models,
    }
