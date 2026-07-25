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
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from backend.core.database import Client

from backend.core.database import get_db
from backend.services.scoring import evaluate_opportunity
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
        # Variante canonica (scrematura) + fascia di condizione.
        "variantKey": row.get("variant_key"),
        "conditionTier": row.get("condition_tier"),
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


def _variant_market_avgs(db: Client, table: str) -> dict[str, float]:
    """Media di mercato per VARIANTE canonica — la scrematura pulita.

    Calcolata dai listing ATTIVI e SANI (esclude rotti/incidentati), raggruppati
    per ``variant_key`` (modello+memoria tech / modello+generazione auto) e
    ripuliti con IQR. Così un iPhone 13 Pro non inquina la media del 13 base.
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
            # "auto" = catch-all di righe storiche senza target: media mista,
            # inutile → si ripiega sulla media del target.
            continue
        if not is_healthy(row.get("condition_tier") or "buono"):
            continue
        buckets.setdefault(vk, []).append(price)

    avgs: dict[str, float] = {}
    for vk, prices in buckets.items():
        cleaned = _iqr_clean(prices)
        if len(cleaned) >= 3:
            avgs[vk] = round(statistics.fmean(cleaned), 2)
    return avgs


def list_opportunities(
    category: str,
    limit: int = 60,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """Live Sniper feed: opportunità di una categoria, dalle più recenti.

    Instrada sulla tabella per-tipo, risolve il nome modello via target_id,
    arricchisce con la media di mercato (margini) e i cali di prezzo storici.
    """
    db = client or get_db()
    table = _opportunities_table(category)
    target_cat = _target_category(category)

    rows = (
        db.table(table)
        .select("*")
        .order("found_at", desc=True)
        .limit(limit)
        .execute()
    ).data or []
    if not rows:
        return []

    targets = _targets_for_category(db, target_cat)  # target_id → model name
    avg_by_target, avg_by_model = _market_avgs(db, target_cat)
    variant_avgs = _variant_market_avgs(db, table)  # scrematura per variante
    price_history = _latest_price_history(db, [row["id"] for row in rows])
    seller_counts = _seller_active_counts(db, table, rows)

    # Valutazione km-aware (solo auto): un modello di regressione per target.
    km_models: dict[str, tuple[float, float, int]] = {}
    if target_cat == "automobile":
        auto_targets = list(
            {row["target_id"] for row in rows if row.get("target_id") and row.get("km")}
        )
        km_models = _km_price_models(db, table, auto_targets)

    result = []
    for row in rows:
        target_id = row.get("target_id")
        model = targets.get(target_id)
        # Media per VARIANTE canonica (scrematura pulita) come primaria; fallback
        # al target (isolamento per generazione) e poi al modello.
        variant_key = row.get("variant_key")
        market_avg = variant_avgs.get(variant_key) if variant_key else None
        if market_avg is None:
            market_avg = avg_by_target.get(target_id)
        if market_avg is None and model:
            market_avg = avg_by_model.get(model)
        shaped = _shape_opportunity(
            row, model, market_avg, price_history.get(row["id"])
        )

        # Storico venditore (A3): quanti annunci attivi ha questo venditore.
        seller_id = row.get("seller_id")
        shaped["sellerActiveCount"] = (
            seller_counts.get(seller_id) if seller_id else None
        )

        # Valutazione km-aware (A1): prezzo atteso PER QUESTI km e margine vero.
        shaped["expectedPrice"] = None
        shaped["marginVsExpected"] = None
        km_model = km_models.get(target_id) if target_id else None
        if km_model and row.get("km") and shaped["askingPrice"]:
            slope, intercept, _n = km_model
            expected = intercept + slope * float(row["km"])
            if expected > 0:
                shaped["expectedPrice"] = round(expected, 2)
                shaped["marginVsExpected"] = round(
                    expected - shaped["askingPrice"], 2
                )

        # Deal Score + assistente trattativa (C2/C4/T3/A2).
        shaped.update(
            evaluate_opportunity(
                category=target_cat,
                title=shaped["title"],
                asking=shaped["askingPrice"],
                market_avg=market_avg,
                margin_pct=shaped["marginPct"],
                found_at=row.get("found_at"),
                seller_type=row.get("seller_type"),
                defects=shaped["defects"],
                urgency=shaped["urgencyFlags"],
                features=shaped["features"],
                battery_pct=shaped["batteryPct"],
                has_price_drop=shaped["priceDrop"] is not None,
            )
        )
        result.append(shaped)
    return result


def _time_to_sale(
    db: Client, table: str, targets: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], float | None]:
    """Time-to-sale (C3): giorni medi found_at→rimozione, per modello.

    Il Garbage Collector marca 'venduto_rimosso' aggiornando updated_at: la
    differenza con found_at misura in quanti giorni l'annuncio è sparito dal
    mercato → liquidità reale del modello. Ritorna (per_modello, mediana
    complessiva del verticale).
    """
    try:
        rows = (
            db.table(table)
            .select("target_id, found_at, updated_at")
            .in_("status", list(_SOLD_STATUSES))
            .order("updated_at", desc=True)
            .limit(2000)
            .execute()
        ).data or []
    except Exception:
        return {}, None

    samples_by_model: dict[str, list[float]] = {}
    all_samples: list[float] = []
    for row in rows:
        found = _parse_ts(row.get("found_at"))
        removed = _parse_ts(row.get("updated_at"))
        if not found or not removed:
            continue
        days = (removed - found).total_seconds() / 86400
        if not (0 <= days <= 365):
            continue
        model = targets.get(row.get("target_id"))
        if model:
            samples_by_model.setdefault(model, []).append(days)
        all_samples.append(days)

    per_model = {
        model: {
            "avgDaysToSell": round(statistics.fmean(days), 1),
            "sampleSold": len(days),
        }
        for model, days in samples_by_model.items()
    }
    overall = round(statistics.median(all_samples), 1) if all_samples else None
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

    # Liquidità (time-to-sale) e prezzi di rivendita suggeriti, per modello.
    targets = _targets_for_category(db, target_cat)
    tts_by_model, overall_tts = _time_to_sale(db, table, targets)
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
        tts = tts_by_model.get(name) or {}
        resale = resale_by_model.get(name) or {}
        models.append(
            {
                "name": name,
                "avg": latest_avg,
                "sample": latest.get("volume"),
                "changePct": change_pct,
                # Liquidità (C3): in quanti giorni ruota questo modello.
                "avgDaysToSell": tts.get("avgDaysToSell"),
                "sampleSold": tts.get("sampleSold"),
                # Prezzi di rivendita suggeriti (C7).
                "fastSalePrice": resale.get("fastSalePrice"),
                "maxSalePrice": resale.get("maxSalePrice"),
                # Serie storica completa (C6): curva di deprezzamento.
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
