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
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.parse import urlparse

from backend.core.database import Client

from backend.core.database import get_db, has_column
from backend.scrapers.nlp_parser import _is_accessory_listing
from backend.services.depreciation import carry_cost_by_variant
from backend.services.scoring import car_risk_assessment, evaluate_opportunity, risk_assessment
from backend.services.survival import EXPIRY_DAYS, removal_kind, survival_summary
from backend.services.valuation import SortedPrices, car_expected_price, evaluate_value, fit_car_price_model
from backend.services.variants import (
    AUTO_ONLY_DEFECTS, CAR_GEN_SEP, car_generation_label, car_is_coupe, car_model_label,
    iphone_model_key,
    is_healthy, model_text,
    year_fits_generation,
)

logger = logging.getLogger(__name__)

_LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")

_ACTIVE_STATUSES = ("nuovo", "visto")
_SOLD_STATUSES = ("venduto_rimosso", "scaduto")

# Le due tabelle non hanno le stesse colonne: chiedere una colonna dell'altro
# verticale fa fallire l'intera query (500 sul feed auto, o — peggio — analitiche
# vuote dentro un try/except, che sembrano "dati non ancora sufficienti").
_TECH_ONLY_COLUMNS = frozenset({"storage_gb", "battery_pct", "ai_analysis"})
_AUTO_ONLY_COLUMNS = frozenset({"year", "km", "transmission", "fuel"})
# Dati strutturati auto (migrazione 23): solo se la colonna esiste già.
_CAR_STRUCT_COLUMNS = frozenset({"car_brand", "car_model", "car_version", "power_kw", "body_type",
                                 "doors", "register_month", "emission_class"})


def _cols(table: str, *names: str) -> str:
    """Lista di colonne per una select, senza quelle assenti in quel verticale."""
    drop = _TECH_ONLY_COLUMNS if table.endswith("_auto") else _AUTO_ONLY_COLUMNS | _CAR_STRUCT_COLUMNS
    cols = [n for n in names if n not in drop
            and (n not in _CAR_STRUCT_COLUMNS or has_column(table, n))]
    # Data di pubblicazione su Subito (migrazione 19) accanto a found_at: è la
    # vera nascita dell'annuncio (vedi _born). Solo se la colonna esiste già.
    if "found_at" in cols and has_column(table, "published_at"):
        cols.append("published_at")
    return ", ".join(cols)


def _born(row: dict[str, Any]) -> datetime | None:
    """Quando l'annuncio è uscito: published_at (da Subito) se c'è, altrimenti
    found_at (quando l'abbiamo visto). Per un annuncio recuperato da un
    backfill found_at arriva giorni dopo e sottostimerebbe età e tempo di
    vendita."""
    return _parse_ts(row.get("published_at") or row.get("found_at"))


def _entry_days(row: dict[str, Any], born: datetime) -> float:
    """Età dell'annuncio quando l'abbiamo visto la prima volta: l'entrata
    ritardata del Kaplan–Meier (vedi survival.kaplan_meier)."""
    found = _parse_ts(row.get("found_at"))
    return max(0.0, (found - born).total_seconds() / 86400) if found else 0.0

# Giorni di permanenza in stock assunti quando i venduti non bastano ancora a
# misurarli davvero (serve al costo di magazzino nel tetto d'acquisto). Un mese
# è la stima prudente: appena il Garbage Collector accumula venduti, subentra
# il dato reale per modello.
DEFAULT_HOLD_DAYS = 30

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
    if category == "automobile":
        return {row["id"]: row["model"] for row in rows.data or []}
    return {row["id"]: _canonical_model_name(row["model"]) for row in rows.data or []}


def _targets_for_category(db: Client, category: str) -> dict[str, str]:
    """target_id → query (nome modello) per la categoria richiesta."""
    rows = (
        db.table("target_models")
        .select("id, query")
        .eq("category", category)
        .execute()
    )
    if category == "automobile":
        return {row["id"]: row["query"] for row in rows.data or []}
    return {row["id"]: _canonical_model_name(row["query"]) for row in rows.data or []}


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
    """listing_id → ultimo CALO di prezzo (old_price/new_price/changed_at)."""
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
        # Lo storico contiene anche i rialzi: qui servono solo i cali.
        old, new = _to_float(row.get("old_price")), _to_float(row.get("new_price"))
        if old is None or new is None or new >= old:
            continue
        # order desc → prima occorrenza per listing_id è la più recente.
        latest.setdefault(row["listing_id"], row)
    return latest


def _price_watch(
    db: Client, listing_ids: list[str]
) -> dict[str, dict[str, Any]]:
    """listing_id → sintesi dello storico prezzi (E — Watch di prezzo).

    Aggrega TUTTI i record di ``price_history`` del singolo annuncio in un
    segnale unico: quante volte ha ribassato, di quanto in totale rispetto al
    primo prezzo visto e da quanti giorni è fermo all'ultimo prezzo. Più
    ribassi / calo maggiore = venditore più motivato (leva di trattativa)."""
    if not listing_ids:
        return {}
    try:
        rows = (
            db.table("price_history")
            .select("listing_id, old_price, new_price, changed_at")
            .in_("listing_id", listing_ids)
            .order("changed_at", desc=False)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}

    by_listing: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_listing.setdefault(row["listing_id"], []).append(row)

    out: dict[str, dict[str, Any]] = {}
    for lid, recs in by_listing.items():
        # changed_at asc → recs[0] = più vecchio, recs[-1] = più recente.
        first = _to_float(recs[0].get("old_price"))
        current = _to_float(recs[-1].get("new_price"))
        drops = rises = 0
        last_drop: dict[str, Any] | None = None
        for r in recs:
            old = _to_float(r.get("old_price"))
            new = _to_float(r.get("new_price"))
            if old is not None and new is not None and new < old:
                drops += 1
                last_drop = r
            elif old is not None and new is not None and new > old:
                rises += 1
        total_eur = total_pct = None
        if first is not None and current is not None and first > current:
            total_eur = round(first - current, 2)
            total_pct = round(total_eur / first * 100, 1) if first > 0 else None
        if drops <= 0 and total_eur is None:
            continue
        # Lo storico ha anche i rialzi: "ultimo ribasso" è l'ultimo CALO.
        last_at = (last_drop or recs[-1]).get("changed_at")
        last_dt = _parse_ts(last_at)
        days_since = (
            max(0, (datetime.now(timezone.utc) - last_dt).days) if last_dt else None
        )
        # Livello di motivazione del venditore dal comportamento sul prezzo.
        if drops >= 2 or (total_pct is not None and total_pct >= 10):
            level = "alto"
        elif drops >= 1 or total_eur is not None:
            level = "medio"
        else:
            level = "basso"
        out[lid] = {
            "firstPrice": first,
            "currentPrice": current,
            "dropCount": drops,
            # Rialzi dopo la pubblicazione: il venditore non ha fretta.
            "riseCount": rises,
            "totalDropEur": total_eur,
            "totalDropPct": total_pct,
            "lastDropAt": last_at,
            "daysSinceLastDrop": days_since,
            "motivation": level,
        }
    return out


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _seller_profiles(
    db: Client, table: str, rows: list[dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """seller_id → profilo venditore (intelligence, leva di trattativa).

    Per ogni venditore degli annunci nel lotto: quanti annunci attivi ha, quanti
    ne ha già venduti e in quanti giorni, e quanto spesso ribassa (segnale di
    disponibilità a trattare). Un venditore che vende in fretta o ribassa spesso
    è "motivato" → più margine di trattativa.
    """
    seller_ids = list({r.get("seller_id") for r in rows if r.get("seller_id")})
    if not seller_ids:
        return {}
    try:
        found = (
            db.table(table)
            .select(_cols(table, "seller_id", "status", "asking_price", "original_price",
                          "found_at", "updated_at", "seller_type"))
            .in_("seller_id", seller_ids)
            .limit(20000)
            .execute()
        ).data or []
    except Exception:
        return {}

    agg: dict[str, dict[str, Any]] = {}
    for row in found:
        sid = row.get("seller_id")
        if not sid:
            continue
        d = agg.setdefault(
            sid,
            {"active": 0, "sold": 0, "days": [], "listed": 0, "drops": 0,
             "dropPcts": [], "type": row.get("seller_type")},
        )
        status = row.get("status")
        if status in _ACTIVE_STATUSES:
            d["active"] += 1
        elif status in _SOLD_STATUSES:
            d["sold"] += 1
            found_ts = _born(row)
            removed_ts = _parse_ts(row.get("updated_at"))
            if found_ts and removed_ts:
                days = (removed_ts - found_ts).total_seconds() / 86400
                if 0 <= days <= 365:
                    d["days"].append(days)
        d["listed"] += 1
        orig = _to_float(row.get("original_price"))
        ask = _to_float(row.get("asking_price"))
        if orig and ask and orig > ask:
            d["drops"] += 1
            d["dropPcts"].append((orig - ask) / orig * 100)

    profiles: dict[str, dict[str, Any]] = {}
    for sid, d in agg.items():
        avg_days = round(statistics.fmean(d["days"]), 1) if d["days"] else None
        drop_rate = round(d["drops"] / d["listed"] * 100) if d["listed"] else 0
        avg_drop_pct = round(statistics.fmean(d["dropPcts"]), 1) if d["dropPcts"] else None
        motivated = bool((avg_days is not None and avg_days <= 14) or drop_rate >= 40)
        profiles[sid] = {
            "active": d["active"],
            "sold": d["sold"],
            "avgDaysToSell": avg_days,
            "dropRate": drop_rate,
            "avgDropPct": avg_drop_pct,
            "type": d["type"],
            "motivated": motivated,
        }
    return profiles


def car_attributes(row: dict[str, Any]) -> dict[str, Any]:
    """Attributi di un'auto per il modello di prezzo: kW, coupé/cabrio,
    diesel, automatico (dai campi strutturati, o dal testo se mancano)."""
    text = f"{row.get('title') or ''} {row.get('description') or ''}"
    body = (row.get("body_type") or "").lower()
    return {
        "kw": row.get("power_kw"),
        "coupe": "coup" in body or "cabrio" in body or (not body and car_is_coupe(text)),
        "diesel": "diesel" in (row.get("fuel") or "").lower(),
        "automatic": (row.get("transmission") or "").lower().startswith(("autom", "sequen")),
    }


def _car_price_models(db: Client, table: str) -> dict[str, dict[str, Any]]:
    """Modello prezzo ~ età + km per VARIANTE auto (modello@generazione), dagli
    annunci attivi SANI con anno e km. Varianti incerte (@nd) o escluse
    (@escluso) non hanno modello: lì l'auto resta senza valore equo.
    Vedi ``valuation.fit_car_price_model`` per le soglie di accettazione."""
    try:
        rows = _select_all(
            lambda: db.table(table)
            # Niente descrizione: su mezzo milione di auto pesa centinaia di MB e la
            # carrozzeria arriva dal campo strutturato (dal titolo se manca).
            .select(_cols(table, "variant_key", "year", "km", "asking_price", "condition_tier", "title",
                          "power_kw", "body_type", "fuel", "transmission"))
            .in_("status", list(_ACTIVE_STATUSES))
        )
    except Exception:
        return {}
    by_variant: dict[str, list[tuple[int, int, float]]] = {}
    for r in rows:
        vk = r.get("variant_key") or ""
        if CAR_GEN_SEP not in vk or vk.endswith(("@nd", "@escluso")):
            continue
        if not is_healthy(r.get("condition_tier") or "buono"):
            continue
        price = _to_float(r.get("asking_price"))
        if (r.get("year") and r.get("km") is not None and price
                and year_fits_generation(vk, r["year"])):
            by_variant.setdefault(vk, []).append(
                {"year": int(r["year"]), "km": int(r["km"]), "price": price, **car_attributes(r)}
            )
    models = {}
    for vk, pts in by_variant.items():
        fitted = fit_car_price_model(pts)
        if fitted:
            models[vk] = fitted
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

    found = _born(row)
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
        "publishedAt": row.get("published_at"),
        "daysOnline": days_online,
        "source": "Subito",
        "status": row.get("status"),
        "triage": row.get("triage"),  # None | 'salvato' | 'scartato'
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
        # Analisi AI locale della descrizione (None finché non processata).
        "ai": row.get("ai_analysis"),
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
            .select("variant_key, asking_price, condition_tier, title")
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
        if _is_accessory_listing(row.get("title")):
            continue
        buckets.setdefault(vk, []).append(price)

    pools: dict[str, list[float]] = {}
    for vk, prices in buckets.items():
        cleaned = _iqr_clean(prices)
        if len(cleaned) >= 3:
            pools[vk] = SortedPrices(cleaned)  # ordinati una volta sola
    return pools


# Campione minimo di venduti per fidarsi del prezzo di realizzo come riferimento.
_MIN_SOLD_REF = 5

# Un annuncio che sparisce entro N giorni è quasi certamente VENDUTO; uno che
# resta a lungo e poi sparisce è spesso scaduto/ritirato invenduto — al suo
# prezzo (troppo alto) nessuno ha comprato. Misurato sui dati reali: chi sparisce
# entro 4gg costa ~13% meno di chi ci mette 12+gg. Includere anche i lenti alza
# il riferimento di rivendita di ~6% in media (fino a -40% sulle varianti
# rumorose), ed è la causa principale del "valore equo troppo alto".
_SALE_WINDOW_DAYS = 10


def _days_between(found_at: Any, updated_at: Any) -> float | None:
    start, end = _parse_ts(found_at), _parse_ts(updated_at)
    if start is None or end is None:
        return None
    return (end - start).total_seconds() / 86400


def _sold_variant_refs(db: Client, table: str) -> dict[str, dict[str, tuple[float, int]]]:
    """Prezzo di RIVENDITA realistico per VARIANTE canonica, dai venduti.

    Ritorna ``{variant_key: {tier_o_"__all__": (mediana, n)}}``: sia il
    riferimento per FASCIA DI CONDIZIONE specifica (quando ci sono abbastanza
    venduti in quella fascia) sia un riferimento "__all__" che mescola le
    fasce sane come fallback. Distinguere i due evita di applicare il
    fattore-condizione (fascia sopra/sotto la media) sopra un prezzo che è
    già la mediana della fascia — altrimenti si conta due volte lo stesso
    aggiustamento. Vedi ``estimate_fair_value``.

    Conta solo gli annunci spariti entro ``_SALE_WINDOW_DAYS`` (venduti davvero,
    non scaduti invenduti); se una variante non raggiunge il campione minimo
    nella finestra, ripiega su tutti i suoi venduti pur di avere un riferimento.
    Scarta accessori/ricambi anche a posteriori: le righe salvate prima del
    filtro allo scraping resterebbero altrimenti a inquinare le mediane.
    """
    try:
        rows = (
            db.table(table)
            .select(_cols(table, "variant_key", "asking_price", "condition_tier", "title",
                          "found_at", "updated_at"))
            .in_("status", list(_SOLD_STATUSES))
            # I più recenti: oltre il tetto restano fuori i venduti vecchi, non
            # un sottoinsieme qualsiasi.
            .order("updated_at", desc=True)
            .limit(20000)
            .execute()
            .data
            or []
        )
    except Exception:
        return {}

    # bucket[vk][tier] = (prezzi_in_finestra, prezzi_tutti)
    buckets: dict[str, dict[str, tuple[list[float], list[float]]]] = {}
    for row in rows:
        vk = row.get("variant_key")
        price = _to_float(row.get("asking_price"))
        tier = row.get("condition_tier") or "buono"
        if not vk or vk == "auto" or price is None or price <= 0:
            continue
        if not is_healthy(tier) or _is_accessory_listing(row.get("title")):
            continue
        days = _days_between(row.get("published_at") or row.get("found_at"), row.get("updated_at"))
        in_window = days is not None and days <= _SALE_WINDOW_DAYS
        vk_buckets = buckets.setdefault(vk, {})
        for key in ("__all__", tier):
            fast, every = vk_buckets.setdefault(key, ([], []))
            every.append(price)
            if in_window:
                fast.append(price)

    refs: dict[str, dict[str, tuple[float, int]]] = {}
    for vk, tier_buckets in buckets.items():
        vk_refs: dict[str, tuple[float, int]] = {}
        for tier, (fast, every) in tier_buckets.items():
            cleaned = _iqr_clean(fast)
            if len(cleaned) < _MIN_SOLD_REF:
                cleaned = _iqr_clean(every)  # copertura prima di precisione
            if len(cleaned) >= _MIN_SOLD_REF:
                vk_refs[tier] = (round(statistics.median(cleaned), 2), len(cleaned))
        if vk_refs:
            refs[vk] = vk_refs
    return refs


def _model_key(variant_key: str | None) -> str | None:
    """Chiave modello = variante senza il suffisso memoria (iphone-13-pro-max-256
    → iphone-13-pro-max) o senza la generazione per le auto (bmw-125i@f2x →
    bmw-125i). Serve per filtrare per modello senza ambiguità."""
    if not variant_key or variant_key == "auto":
        return None
    if CAR_GEN_SEP in variant_key:
        return variant_key.split(CAR_GEN_SEP, 1)[0]
    head, _, last = variant_key.rpartition("-")
    # Toglie solo un suffisso di memoria (128, 1024, na): "bmw-123d" resta
    # intero (prima diventava "bmw" e tutte le auto finivano sotto "Bmw").
    return head if head and (last.isdigit() or last == "na") else variant_key


def _model_label(model_key: str) -> str:
    """iphone-13-pro-max → 'iPhone 13 Pro Max'; iphone-16e → 'iPhone 16e'."""
    parts = model_key.split("-")
    if parts and parts[0] == "iphone":
        def word(p: str) -> str:
            if p[:1].isdigit():
                return p                      # 13, 16e, 6s
            if p in ("x", "xr", "xs", "se"):
                return p.upper()              # X, XR, XS, SE
            return "mini" if p == "mini" else p.capitalize()
        rest = " ".join(word(p) for p in parts[1:])
        return f"iPhone {rest}".strip()
    return car_model_label(model_key) or model_key.replace("-", " ").title()


def _row_model(row: dict[str, Any], targets: dict[str, str]) -> str | None:
    """Modello della riga per le statistiche. Tech: dalla variante canonica
    (cioè dal TITOLO dell'annuncio), così entrano anche gli iPhone senza target
    e nessuno finisce sotto il modello della query che l'ha trovato. Auto (o
    variante non riconosciuta): dal target, come prima."""
    mk = _model_key(row.get("variant_key"))
    if mk and mk.startswith("iphone-"):
        label = _model_label(mk)
        # Andata e ritorno: la chiave vale solo se il resolver, riletto il nome,
        # ridà la stessa chiave. Scarta le varianti "di ripiego" ricavate dal
        # titolo (iphone-128gb-nero-...) e i modelli inesistenti salvati da
        # versioni precedenti del resolver (iphone-12e, iphone-17-mini).
        if iphone_model_key(label) == mk:
            return label
    if mk and car_model_label(mk):
        return car_model_label(mk)
    if mk and CAR_GEN_SEP in (row.get("variant_key") or ""):
        # Auto con dati strutturati di Subito: il modello è marca + modello
        # ("Bmw Serie 1"), non il target che l'ha trovata.
        return _model_label(mk)
    return targets.get(row.get("target_id"))


def _canonical_model_name(name: str | None) -> str | None:
    """Nome di target/prodotto allineato all'etichetta di _row_model
    ("iPhone 17 Air" → "iPhone Air"), così le chiavi per modello combaciano."""
    key = iphone_model_key(name)
    return _model_label(key) if key else name


_PAGE_ROWS = 5000


def _select_all(make_query: Any) -> list[dict[str, Any]]:
    """Tutte le righe di una select, a pagine (ordinate per id: offset stabile).
    Le statistiche devono vedere l'intero stock, non un tetto arbitrario: con la
    copertura totale gli attivi tech sono decine di migliaia."""
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = (
            make_query().order("id").range(start, start + _PAGE_ROWS - 1).execute().data
            or []
        )
        rows.extend(page)
        if len(page) < _PAGE_ROWS:
            return rows
        start += _PAGE_ROWS


_facets_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _opportunity_facets(db: Client, table: str) -> dict[str, Any]:
    """Valori disponibili per i filtri, con cache per le auto (_CTX_TTL_S):
    contarli su mezzo milione di annunci a ogni richiesta costa secondi."""
    import time  # noqa: PLC0415

    if table.endswith("_auto"):
        hit = _facets_cache.get(table)
        if hit and time.monotonic() - hit[0] < _CTX_TTL_S:
            return hit[1]
        facets = _compute_facets(db, table)
        _facets_cache[table] = (time.monotonic(), facets)
        return facets
    return _compute_facets(db, table)


def _compute_facets(db: Client, table: str) -> dict[str, Any]:
    """Valori disponibili per i filtri (modello/memoria/colore/condizione) con
    conteggi, dai listing attivi — popola i menu a tendina della dashboard."""
    rows = (
        db.table(table)
        .select(_cols(table, "variant_key", "storage_gb", "color", "condition_tier",
                      "year", "transmission", "fuel"))
        .in_("status", list(_ACTIVE_STATUSES))
        .execute()
        .data
        or []
    )
    models: Counter = Counter()
    storages: Counter = Counter()
    colors: Counter = Counter()
    conditions: Counter = Counter()
    # Auto: generazione (dalla variante), cambio, alimentazione, anni.
    generations: Counter = Counter()
    transmissions: Counter = Counter()
    fuels: Counter = Counter()
    years: list[int] = []
    for r in rows:
        vk = r.get("variant_key") or ""
        if CAR_GEN_SEP in vk:
            label = f"{car_model_label(_model_key(vk)) or _model_key(vk)} {car_generation_label(vk)}"
            generations[vk, label] += 1
        if r.get("transmission"):
            transmissions[r["transmission"]] += 1
        if r.get("fuel"):
            fuels[r["fuel"]] += 1
        if r.get("year"):
            years.append(int(r["year"]))
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
        "generations": [
            {"value": vk, "label": label, "count": c}
            for (vk, label), c in sorted(generations.items(), key=lambda x: -x[1])
        ],
        "transmissions": [{"value": k, "count": c} for k, c in transmissions.most_common()],
        "fuels": [{"value": k, "count": c} for k, c in fuels.most_common()],
        "yearRange": [min(years), max(years)] if years else None,
    }


def _build_enrich_ctx(
    db: Client, target_cat: str, table: str, rows: list[dict[str, Any]]
) -> dict[str, Any]:
    """Contesto condiviso per l'arricchimento di un lotto di righe (pool per
    variante, target, storico prezzi, venditori, regressione km). Costruito una
    sola volta per lotto — riusato da ``list_opportunities`` e ``enrich_for_alerts``."""
    # Aggiorna margine obiettivo / prezzi ricambi dalle Impostazioni UI prima
    # di valutare il lotto (max_bid, radar riparazioni).
    from backend.services import settings_store

    settings_store.get_all()

    row_ctx = {
        "price_history": _latest_price_history(db, [r["id"] for r in rows]),
        "price_watch": _price_watch(db, [r["id"] for r in rows]),
        "seller_profiles": _seller_profiles(db, table, rows),
    }
    # La parte che non dipende dalle righe (pool, modelli di prezzo, venduti,
    # medie, matrice) costa secondi e cambia lentamente → in cache: 15' per le
    # auto (mezzo milione di annunci), 5' per gli iPhone.
    import time  # noqa: PLC0415

    ttl = _CTX_TTL_S if target_cat == "automobile" else _CTX_TTL_TECH_S
    hit = _ctx_cache.get(table)
    if hit and time.monotonic() - hit[0] < ttl:
        return {**hit[1], **row_ctx}
    base = _build_base_ctx(db, target_cat, table)
    _ctx_cache[table] = (time.monotonic(), base)
    return {**base, **row_ctx}


_CTX_TTL_S = 900
_CTX_TTL_TECH_S = 300
_ctx_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _build_base_ctx(db: Client, target_cat: str, table: str) -> dict[str, Any]:
    """Parte del contesto che non dipende dalle righe da arricchire."""
    ctx: dict[str, Any] = {
        "target_cat": target_cat,
        "targets": _targets_for_category(db, target_cat),
        "variant_pools": _variant_price_pools(db, table),
        "sold_refs": _sold_variant_refs(db, table),
        "car_models": {},
    }
    # Quanto vale meno un riparato aftermarket (schermo/batteria non originali),
    # misurato sul mercato dalla matrice riparazioni (in cache 5').
    ctx["non_original_ratios"] = {}
    if target_cat != "automobile":
        try:
            from backend.services.repair_matrix import get_repair_matrix  # noqa: PLC0415

            ctx["non_original_ratios"] = {
                k: v["ratio"] for k, v in get_repair_matrix()["nonOriginalRatios"].items()
            }
        except Exception:
            logger.exception("Rapporti parti non originali non disponibili")
    avg_by_target, avg_by_model = _market_avgs(db, target_cat)
    ctx["avg_by_target"] = avg_by_target
    ctx["avg_by_model"] = avg_by_model
    # Giorni medi di vendita per modello (dai venduti) → ROI per giorno di capitale.
    sold_by_model, _overall = _sold_stats(db, table, ctx["targets"])
    # Per ROI e costo di magazzino conta il tempo ONESTO (Kaplan–Meier); se meno
    # di metà si è venduta in finestra si ripiega sulla media dei venduti.
    ctx["sold_days"] = {
        m: s.get("daysToSellKM") or s["avgDaysToSell"]
        for m, s in sold_by_model.items()
        if s.get("daysToSellKM") or s.get("avgDaysToSell")
    }
    # Deprezzamento mensile per variante (curva di deprezzamento) → costo di
    # magazzino nel tetto d'acquisto. Solo tech: le varianti auto sono per
    # generazione, non per età del modello.
    ctx["carry_month"] = (
        carry_cost_by_variant(ctx["variant_pools"]) if target_cat != "automobile" else {}
    )
    if target_cat == "automobile":
        ctx["car_models"] = _car_price_models(db, table)
    return ctx


def enrich_for_alerts(
    category: str, rows: list[dict[str, Any]], client: Client | None = None
) -> list[dict[str, Any]]:
    """Arricchisce un lotto di righe (le NUOVE di un giro sniper) con la stessa
    intelligence della dashboard — valore equo per variante, classe affare,
    Deal Score, offerta consigliata, radar riparazioni, anti-truffa AI.

    Serve agli alert Telegram "intelligenti": si notifica solo ciò che la BI
    considera davvero un affare, non il margine grezzo contro una media."""
    if not rows:
        return []
    db = client or get_db()
    table = _opportunities_table(category)
    target_cat = _target_category(category)
    ctx = _build_enrich_ctx(db, target_cat, table, rows)
    return [_enrich_opportunity(r, ctx) for r in rows]


def _enrich_opportunity(row: dict[str, Any], ctx: dict[str, Any]) -> dict[str, Any]:
    """Arricchisce una riga con margine, variante, valutazione, Deal Score e
    assistente di trattativa (il cuore BI, per singola opportunità)."""
    target_id = row.get("target_id")
    model = _row_model(row, ctx["targets"])
    variant_key = row.get("variant_key")
    pool = ctx["variant_pools"].get(variant_key) if variant_key else None
    market_avg = round(statistics.fmean(pool), 2) if pool and len(pool) >= 3 else None
    if market_avg is None:
        market_avg = ctx["avg_by_target"].get(target_id)
    if market_avg is None and model:
        market_avg = ctx["avg_by_model"].get(model)

    shaped = _shape_opportunity(row, model, market_avg, ctx["price_history"].get(row["id"]))
    # E — Watch di prezzo: storico completo dei ribassi del singolo annuncio
    # (quante volte, quanto, da quanti giorni) → quanto è motivato il venditore.
    shaped["priceWatch"] = ctx.get("price_watch", {}).get(row["id"])

    seller_id = row.get("seller_id")
    profile = ctx["seller_profiles"].get(seller_id) if seller_id else None
    shaped["sellerProfile"] = profile
    shaped["sellerActiveCount"] = profile["active"] if profile else None

    shaped["expectedPrice"] = None
    shaped["marginVsExpected"] = None
    car_model = ctx["car_models"].get(variant_key) if variant_key else None
    if car_model and not year_fits_generation(variant_key, row.get("year")):
        car_model = None  # anno incompatibile con la generazione: niente stima
    attrs = car_attributes(row) if ctx["target_cat"] == "automobile" else {}
    expected = car_expected_price(car_model, row.get("year"), row.get("km"), attrs)
    if expected and shaped["askingPrice"]:
        # Prezzo atteso di un'auto SANA di quell'anno e km nella sua generazione.
        shaped["expectedPrice"] = expected
        shaped["marginVsExpected"] = round(expected - shaped["askingPrice"], 2)
    shaped["carModel"] = (
        {k: car_model.get(k) for k in ("n", "errPct", "perYearPct", "per10kKmPct", "yearRange",
                                       "kmRange", "kwRange", "per10pctKwPct", "coupePct",
                                       "dieselPct", "automaticPct")}
        if car_model else None
    )

    # Riferimento dai VENDUTI per questa variante (prezzo di realizzo reale, n
    # campioni). Preferisce il riferimento della STESSA fascia di condizione
    # dell'annuncio (in tal caso è già "il prezzo a cui si vende un come-nuovo",
    # niente doppio aggiustamento); sotto soglia ripiega sul mix di fasce sane
    # della variante, poi sui listati.
    tier = row.get("condition_tier") or "buono"
    sold_bucket = ctx["sold_refs"].get(variant_key) if variant_key else None
    sold_tier_specific = bool(sold_bucket and tier in sold_bucket)
    sold_pair = (
        sold_bucket.get(tier) if sold_tier_specific
        else sold_bucket.get("__all__") if sold_bucket
        else None
    )
    sold_reference = sold_pair[0] if sold_pair else None
    sold_n = sold_pair[1] if sold_pair else 0

    valuation = evaluate_value(
        category=ctx["target_cat"],
        asking=shaped["askingPrice"],
        condition_tier=row.get("condition_tier"),
        variant_prices=pool or [],
        km=row.get("km"),
        year=row.get("year"),
        car_model=car_model,
        car_attrs=attrs,
        sold_reference=sold_reference,
        sold_reference_is_tier_specific=sold_tier_specific,
        has_images=bool(row.get("image_urls")),
    )
    shaped.update(valuation)

    # Confidence della valutazione = quanti campioni la sostengono (attivi + venduti).
    samples = len(pool or []) + sold_n
    shaped["valuationSamples"] = samples
    shaped["valuationConfidence"] = (
        "alta" if samples >= 15 else "media" if samples >= 6 else "bassa"
    )

    # ROI per giorno di capitale = margine vs valore equo ÷ giorni medi di
    # vendita del modello (dai venduti). Ordina gli affari per resa reale.
    days = ctx.get("sold_days", {}).get(model)
    shaped["roiPerDayPct"] = (
        round(valuation["marginVsFairPct"] / days, 2)
        if valuation.get("marginVsFairPct") is not None and days and days > 0
        else None
    )

    # Costo di magazzino: deprezzamento della variante × giorni attesi in stock.
    # Finché il Garbage Collector non ha accumulato venduti, i giorni reali non
    # esistono e si assume un mese (DEFAULT_HOLD_DAYS): il payload dichiara
    # quali giorni ha usato, così in UI si vede se è una stima o un dato.
    carry_month = ctx.get("carry_month", {}).get(variant_key)
    hold_days = int(days) if days and days > 0 else DEFAULT_HOLD_DAYS
    shaped["carryCost"] = (
        {
            "monthEur": carry_month,
            "holdDays": hold_days,
            "totalEur": round(carry_month * hold_days / 30),
            "estimatedDays": not (days and days > 0),
        }
        if carry_month
        else None
    )

    score_margin = (
        valuation["marginVsFairPct"]
        if valuation["marginVsFairPct"] is not None
        else shaped["marginPct"]
    )
    shaped.update(
        evaluate_opportunity(
            category=ctx["target_cat"],
            # Il modello (ricambi, fascia) anche dalla descrizione se il titolo tace.
            title=model_text(shaped["title"], row.get("description")),
            asking=shaped["askingPrice"],
            market_avg=valuation["fairValue"] or market_avg,
            margin_pct=score_margin,
            found_at=row.get("published_at") or row.get("found_at"),
            seller_type=row.get("seller_type"),
            defects=shaped["defects"],
            urgency=shaped["urgencyFlags"],
            features=shaped["features"],
            battery_pct=shaped["batteryPct"],
            has_price_drop=shaped["priceDrop"] is not None,
            # Tetto d'acquisto sul realizzo reale (venduti sani) se disponibile,
            # al netto del deprezzamento maturato mentre resta invenduto.
            resale_ref=sold_reference or market_avg,
            carry_month_eur=carry_month,
            hold_days=hold_days,
            non_original_ratios=ctx.get("non_original_ratios"),
        )
    )
    # Anti-truffa affinato con l'AI locale:
    #  - se l'AI vede un rischio truffa ALTO → forza sospetto (anche se il prezzo
    #    sembra normale);
    #  - se il prezzo è "sospetto" (troppo basso) MA l'AI trova un motivo
    #    LEGITTIMO (upgrade, regalo non gradito, urgenza) → NON è una truffa ma
    #    un vero affare: si toglie il flag e si tiene lo score.
    ai = row.get("ai_analysis") or {}
    ai_scam_high = ai.get("rischio_truffa") == "alto"
    ai_legit = ai.get("categoria_motivo") == "legittimo"

    is_suspect = valuation["dealClass"] == "sospetto"
    if is_suspect and ai_legit and not ai_scam_high:
        shaped["dealClass"] = "affare"  # motivo legittimo → affare, non truffa
    elif is_suspect or ai_scam_high:
        shaped["dealClass"] = "sospetto"
        shaped["score"] = 0
        shaped["scoreBreakdown"] = [
            {"label": "⚠️ Prezzo sospetto (possibile truffa/errore)", "points": 0}
        ]

    # Risk Score anti-frode: aggrega i segnali di rischio (iCloud lock, pattern
    # truffa a distanza, prezzo sospetto, finto privato, venditore senza storico)
    # in un semaforo unico e visibile. Usa il dealClass FINALE (post-AI).
    if ctx["target_cat"] == "automobile":
        shaped["risk"] = car_risk_assessment(
            year=row.get("year"),
            km=row.get("km"),
            title=shaped.get("title"),
            description=shaped.get("description"),
            defects=shaped["defects"],
            deal_class=shaped.get("dealClass"),
            seller_type=row.get("seller_type"),
            seller_active=(profile or {}).get("active"),
            has_images=bool(row.get("image_urls")),
        )
    else:
        shaped["risk"] = risk_assessment(
            defects=shaped["defects"],
            description=shaped.get("description"),
            deal_class=shaped.get("dealClass"),
            ai_scam_high=ai_scam_high,
            seller_type=row.get("seller_type"),
            seller_sold_count=(profile or {}).get("sold"),
        )
    return shaped


# Feed arricchito in cache: valutare TUTTO lo stock attivo (decine di migliaia
# di annunci con la copertura totale) costa secondi, e i dati cambiano a ritmo
# di giri di raccolta. Il triage invece si rilegge fresco a ogni richiesta.
_FEED_TTL_S = 90
# Oltre il TTL e fino a qui si serve il vecchio mentre si ricalcola (vedi sopra).
_FEED_STALE_MAX_S = 1800
_feed_refreshing: set[str] = set()
_feed_cache: dict[str, tuple[float, list[tuple[dict[str, Any], dict[str, Any]]]]] = {}


def invalidate_feed_cache() -> None:
    _feed_cache.clear()


# Feed auto: tetto di righe valutate per richiesta e finestra di default.
AUTO_FEED_MAX_ROWS = 5000
AUTO_FEED_DAYS = 7


def _auto_feed_rows(table: str, pre: dict[str, Any]) -> list[dict[str, Any]]:
    """Righe auto filtrate NEL DB (mezzo milione di attive non si valutano in
    memoria a ogni richiesta). Senza filtro di modello/generazione: solo gli
    annunci degli ultimi AUTO_FEED_DAYS giorni. Al massimo AUTO_FEED_MAX_ROWS,
    i più recenti."""
    from backend.core.database import _get_pool  # noqa: PLC0415

    where = ["status in ('nuovo', 'visto')"]
    params: list[Any] = []
    if pre.get("generation"):
        where.append("variant_key = %s")
        params.append(pre["generation"])
    elif pre.get("model"):
        where.append("(variant_key = %s or variant_key like %s)")
        params += [pre["model"], pre["model"] + CAR_GEN_SEP + "%"]
    else:
        where.append("found_at >= now() - make_interval(days => %s)")
        params.append(AUTO_FEED_DAYS)
    for col, op, key in (("year", ">=", "min_year"), ("year", "<=", "max_year"),
                         ("km", "<=", "max_km"), ("asking_price", ">=", "min_price"),
                         ("asking_price", "<=", "max_price")):
        if pre.get(key) is not None:
            where.append(f"{col} {op} %s")
            params.append(pre[key])
    for col in ("transmission", "fuel"):
        if pre.get(col):
            where.append(f"{col} = %s")
            params.append(pre[col])
    if pre.get("q"):
        where.append("title ilike %s")
        params.append(f"%{pre['q']}%")
    sql = (f"select * from public.{table} where {' and '.join(where)} "
           f"order by found_at desc limit %s")
    with _get_pool().connection() as conn:
        return [dict(r) for r in conn.execute(sql, (*params, AUTO_FEED_MAX_ROWS)).fetchall()]


def _enriched_feed(
    db: Client, table: str, target_cat: str, prefilter: dict[str, Any] | None = None
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """(riga, opportunità arricchita) per ogni annuncio attivo, con cache.
    Auto: solo le righe del ``prefilter`` (vedi _auto_feed_rows)."""
    import time  # noqa: PLC0415

    auto = table.endswith("_auto")
    cache_key = f"{table}:{sorted((prefilter or {}).items())}" if auto else table
    hit = _feed_cache.get(cache_key)
    if hit and time.monotonic() - hit[0] < _FEED_TTL_S:
        return hit[1]
    if hit and time.monotonic() - hit[0] < _FEED_STALE_MAX_S:
        # Scaduto ma recente: si risponde SUBITO col vecchio e si ricalcola in
        # background (valutare 47k iPhone costa ~20 s: nessuno deve aspettarli).
        # Il vecchio resta servibile finché il nuovo non è pronto.
        if cache_key not in _feed_refreshing:
            import threading  # noqa: PLC0415

            _feed_refreshing.add(cache_key)

            def refresh() -> None:
                try:
                    _feed_cache[cache_key] = (time.monotonic(),
                                              _build_feed(db, table, target_cat, prefilter))
                except Exception:
                    logger.exception("Ricalcolo del feed in background fallito")
                finally:
                    _feed_refreshing.discard(cache_key)

            threading.Thread(target=refresh, daemon=True).start()
        return hit[1]
    pairs = _build_feed(db, table, target_cat, prefilter)
    if auto and len(_feed_cache) > 50:
        _feed_cache.clear()  # una chiave per combinazione di filtri: non accumulare
    _feed_cache[cache_key] = (time.monotonic(), pairs)
    return pairs


def _build_feed(
    db: Client, table: str, target_cat: str, prefilter: dict[str, Any] | None
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    if table.endswith("_auto"):
        rows = _auto_feed_rows(table, prefilter or {})
    else:
        rows = _select_all(
            lambda: db.table(table).select("*").in_("status", list(_ACTIVE_STATUSES))
        )
        # Accessori e ricambi ("Cover per iPhone 13", "Display iPhone 15"): non
        # sono telefoni e col valore equo della variante sembrerebbero affari
        # clamorosi. Scartati anche QUI, non solo allo scraping, così il filtro
        # vale subito su tutto lo storico già raccolto.
        rows = [r for r in rows if not _is_accessory_listing(r.get("title"))]
    if not rows:
        return []
    ctx = _build_enrich_ctx(db, target_cat, table, rows)
    return [(r, _enrich_opportunity(r, ctx)) for r in rows]


def _current_triage(db: Client, table: str) -> dict[str, str]:
    """id → triage attuale (pochi record: solo salvati/scartati)."""
    try:
        rows = (
            db.table(table).select("id, triage")
            .in_("triage", ["salvato", "scartato"]).execute().data or []
        )
    except Exception:
        return {}
    return {r["id"]: r["triage"] for r in rows}


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
    min_price: float | None = None,
    max_price: float | None = None,
    min_days: int | None = None,
    max_days: int | None = None,
    q: str | None = None,
    view: str = "attivi",
    preset: str | None = None,
    defect: str | None = None,
    only_defect: bool = False,
    min_year: int | None = None,
    max_year: int | None = None,
    max_km: int | None = None,
    transmission: str | None = None,
    fuel: str | None = None,
    generation: str | None = None,
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

    prefilter = (
        {"model": model, "generation": generation, "min_year": min_year, "max_year": max_year,
         "max_km": max_km, "min_price": min_price, "max_price": max_price,
         "transmission": transmission, "fuel": fuel, "q": q}
        if table.endswith("_auto") else None
    )
    pairs = _enriched_feed(db, table, target_cat, prefilter)
    triage = _current_triage(db, table)

    def keep(row: dict[str, Any]) -> bool:
        price = _to_float(row.get("asking_price"))
        if storage is not None and not table.endswith("_auto") and row.get("storage_gb") != storage:
            return False
        if color and row.get("color") != color:
            return False
        if condition and row.get("condition_tier") != condition:
            return False
        if min_price is not None and (price is None or price < min_price):
            return False
        if max_price is not None and (price is None or price > max_price):
            return False
        # Filtri auto (anno, km, cambio, alimentazione, generazione).
        if table.endswith("_auto"):
            year, km = row.get("year"), row.get("km")
            if min_year is not None and (not year or year < min_year):
                return False
            if max_year is not None and (not year or year > max_year):
                return False
            if max_km is not None and (km is None or km > max_km):
                return False
            if transmission and (row.get("transmission") or "") != transmission:
                return False
            if fuel and (row.get("fuel") or "") != fuel:
                return False
            if generation and row.get("variant_key") != generation:
                return False
        # Guasto (dalla matrice riparazioni): l'annuncio lo dichiara; con
        # only_defect è l'UNICO guasto funzionale (segni estetici ammessi).
        if defect:
            found = set(row.get("defects_noted") or []) - {"graffi"} - AUTO_ONLY_DEFECTS
            if defect not in found or (only_defect and found != {defect}):
                return False
        # Triage utente (ortogonale allo status): salvati / nascondi gli scartati.
        state = triage.get(row["id"])
        if view == "salvati":
            return state == "salvato"
        if view != "tutti":  # "attivi" (default): nasconde gli scartati
            return state != "scartato"
        return True

    items = [{**item, "triage": triage.get(row["id"])} for row, item in pairs if keep(row)]
    if not items:
        return {"items": [], "total": 0, "facets": facets}

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
    if min_days is not None:
        items = [
            it for it in items
            if it.get("daysOnline") is not None and it["daysOnline"] >= min_days
        ]
    if max_days is not None:
        items = [
            it for it in items
            if it.get("daysOnline") is not None and it["daysOnline"] <= max_days
        ]
    if q:
        ql = q.strip().lower()
        items = [
            it for it in items
            if ql in (it.get("title") or "").lower()
            or ql in (it.get("location") or "").lower()
        ]

    # Preset rapidi (campi derivati dalla BI).
    if preset == "compra_ora":
        items = [
            it for it in items
            if it.get("buyAtAsking") and it.get("dealClass") != "sospetto"
        ]
    elif preset == "motivati":
        items = [it for it in items if (it.get("sellerProfile") or {}).get("motivated")]
    elif preset == "riparabili":
        items = [
            it for it in items
            if it.get("repair") and (it["repair"].get("netMarginPct") or -1) > 0
        ]

    if sort == "recent":
        items.sort(key=lambda it: it.get("foundAt") or "", reverse=True)
    elif sort == "margin":
        items.sort(
            key=lambda it: it["marginPct"] if it.get("marginPct") is not None else -1e9,
            reverse=True,
        )
    elif sort == "roi":
        items.sort(
            key=lambda it: it["roiPerDayPct"] if it.get("roiPerDayPct") is not None else -1e9,
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


_SOLD_STATS_TTL_S = 300
_sold_stats_cache: dict[str, tuple[float, Any]] = {}


def _sold_stats(
    db: Client, table: str, targets: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], float | None]:
    """Versione con cache (5'): scorre tutto lo stock attivo+sparito, e la
    chiamano sia la dashboard sia gli alert. I dati cambiano a ritmo di giri
    di raccolta, non di richieste."""
    import time  # noqa: PLC0415

    hit = _sold_stats_cache.get(table)
    if hit and time.monotonic() - hit[0] < _SOLD_STATS_TTL_S:
        return hit[1]
    result = _compute_sold_stats(db, table, targets)
    _sold_stats_cache[table] = (time.monotonic(), result)
    return result


def _compute_sold_stats(
    db: Client, table: str, targets: dict[str, str]
) -> tuple[dict[str, dict[str, Any]], float | None]:
    """Statistiche dai VENDUTI (annunci spariti) — il segnale di vendita reale.

    Il Garbage Collector marca 'venduto_rimosso' (annuncio sparito da Subito =
    proxy di venduto) conservando l'ultimo ``asking_price`` e aggiornando
    ``updated_at``. Da qui, per modello: giorni medi di vendita (found→sparizione),
    **prezzo di vendita reale** (mediana/max dei venduti, NON dei listati) e le
    fasce prezzo→giorni. Solo listing sani. Ritorna (per_modello, mediana giorni).
    """
    cols = ("target_id", "variant_key", "asking_price", "found_at", "updated_at",
            "condition_tier", "title")
    try:
        sold_rows = _select_all(
            lambda: db.table(table)
            .select(_cols(table, *cols, "original_price"))
            .in_("status", list(_SOLD_STATUSES))
        )
        active_rows = _select_all(
            lambda: db.table(table)
            .select(_cols(table, *cols))
            .in_("status", list(_ACTIVE_STATUSES))
        )
    except Exception:
        return {}, None

    def usable(row: dict[str, Any]) -> bool:
        return is_healthy(row.get("condition_tier") or "buono") and not _is_accessory_listing(
            row.get("title")
        )

    now = datetime.now(timezone.utc)
    # Gli ATTIVI entrano come "censurati" (non ancora venduti dopo N giorni) e
    # danno la mediana di mercato per riconoscere i ritirati.
    observations: dict[str, list[tuple[float, bool, float]]] = {}
    active_prices: dict[str, list[float]] = {}
    for row in active_rows:
        if not usable(row):
            continue
        model = _row_model(row, targets)
        born = _born(row)
        if not model or not born:
            continue
        observations.setdefault(model, []).append(
            (max(0.0, (now - born).total_seconds() / 86400), False, _entry_days(row, born))
        )
        price = _to_float(row.get("asking_price"))
        if price and price > 0:
            active_prices.setdefault(model, []).append(price)
    market_median = {m: statistics.median(ps) for m, ps in active_prices.items() if len(ps) >= 3}

    by_model: dict[str, list[tuple[float, float]]] = {}
    kinds: dict[str, Counter] = {}
    all_days: list[float] = []
    outflow_7d: dict[str, int] = {}
    cutoff_7d = now - timedelta(days=7)
    for row in sold_rows:
        if not usable(row):
            continue
        model = _row_model(row, targets)
        price = _to_float(row.get("asking_price"))
        found = _born(row)
        removed = _parse_ts(row.get("updated_at"))
        if not model or price is None or price <= 0 or not found or not removed:
            continue
        days = (removed - found).total_seconds() / 86400
        if not (0 <= days <= EXPIRY_DAYS + 30):
            continue
        # Non ogni sparizione è una vendita: scaduti e ritirati restano
        # "censurati" (fino a quel giorno non venduti) e fuori dai prezzi.
        kind = removal_kind(
            days, row.get("original_price") is not None, price, market_median.get(model)
        )
        kinds.setdefault(model, Counter())[kind] += 1
        observations.setdefault(model, []).append((days, kind == "venduto", _entry_days(row, found)))
        if kind != "venduto":
            continue
        by_model.setdefault(model, []).append((price, days))
        all_days.append(days)
        if removed >= cutoff_7d:
            outflow_7d[model] = outflow_7d.get(model, 0) + 1

    per_model: dict[str, dict[str, Any]] = {}
    for model, pts in by_model.items():
        if len(pts) < 3:
            continue
        prices = [p for p, _ in pts]
        days = [d for _, d in pts]
        survival = survival_summary(observations.get(model, []))
        per_model[model] = {
            # Media dei SOLI venduti: ottimista (chi resta online non conta).
            "avgDaysToSell": round(statistics.fmean(days), 1),
            # Kaplan–Meier con gli attivi come censurati: il dato onesto. None =
            # meno di metà degli annunci si è venduta nella finestra osservata.
            "daysToSellKM": survival["medianDays"],
            "sold7dPct": survival["sold7dPct"],
            "sold30dPct": survival["sold30dPct"],
            "censored": survival["censored"],
            "removalKinds": dict(kinds.get(model, {})),
            "sampleSold": len(pts),
            "soldMedian": round(statistics.median(prices)),
            "soldMax": round(max(prices)),
            "outflow7d": outflow_7d.get(model, 0),
            "priceBands": _price_bands(pts),
        }
    overall = round(statistics.median(all_days), 1) if all_days else None
    return per_model, overall


def _active_market_medians(
    db: Client, table: str, targets: dict[str, str]
) -> dict[str, float]:
    """Mediana dei prezzi ATTIVI sani per modello (serve a removal_kind)."""
    rows = _select_all(
        lambda: db.table(table)
        .select("target_id, variant_key, asking_price, condition_tier, title")
        .in_("status", list(_ACTIVE_STATUSES))
    )
    prices: dict[str, list[float]] = {}
    for row in rows:
        if not is_healthy(row.get("condition_tier") or "buono"):
            continue
        if _is_accessory_listing(row.get("title")):
            continue
        model = _row_model(row, targets)
        price = _to_float(row.get("asking_price"))
        if model and price and price > 0:
            prices.setdefault(model, []).append(price)
    return {m: statistics.median(ps) for m, ps in prices.items() if len(ps) >= 3}


def get_time_to_sale(
    category: str,
    client: Client | None = None,
) -> dict[str, Any]:
    """Tempo di vendita affettabile per modello / colore / taglia (e incroci).

    Dai VENDUTI (``venduto_rimosso`` = annuncio sparito da Subito) ritorna i
    fatti grezzi ridotti — modello, colore, memoria, giorni di vendita
    (found→sparizione), prezzo — più i valori distinti di ogni dimensione. Il
    pivot (quali dimensioni incrociare) lo fa la UI, così l'utente combina
    liberamente modello/colore/taglia e legge i giorni medi per ogni fetta.
    Solo listing sani, giorni in [0, 365]."""
    db = client or get_db()
    target_cat = _target_category(category)
    table = _opportunities_table(category)
    targets = _targets_for_category(db, target_cat)
    try:
        rows = _select_all(
            lambda: db.table(table)
            .select(
                _cols(
                    table, "target_id", "variant_key", "color", "storage_gb",
                    "asking_price", "original_price", "found_at", "updated_at",
                    "condition_tier", "title",
                )
            )
            .in_("status", list(_SOLD_STATUSES))
        )
    except Exception:
        rows = []

    try:
        medians = _active_market_medians(db, table, targets)
    except Exception:
        medians = {}
    excluded: Counter = Counter()

    records: list[dict[str, Any]] = []
    models: set[str] = set()
    colors: set[str] = set()
    storages: set[int] = set()
    conditions: set[str] = set()
    for row in rows:
        # La condizione NON si filtra più: è la dimensione che spiega meglio il
        # prezzo, quindi va nel grafico come variabile (non buttata via).
        # Restano fuori solo accessori e ricambi, che non sono telefoni.
        if _is_accessory_listing(row.get("title")):
            continue
        model = _row_model(row, targets)
        found = _born(row)
        removed = _parse_ts(row.get("updated_at"))
        if not model or not found or not removed:
            continue
        days = (removed - found).total_seconds() / 86400
        if not (0 <= days <= EXPIRY_DAYS + 30):
            continue
        price = _to_float(row.get("asking_price"))
        # Solo le sparizioni che sembrano VENDITE: scaduti e ritirati non dicono
        # a che prezzo né in quanto tempo si vende.
        kind = removal_kind(days, row.get("original_price") is not None, price, medians.get(model))
        if kind != "venduto":
            excluded[kind] += 1
            continue
        color = row.get("color")
        storage = row.get("storage_gb")
        tier = row.get("condition_tier") or "buono"
        records.append(
            {
                "model": model,
                "color": color,
                "storageGb": int(storage) if storage else None,
                "conditionTier": tier,
                "days": round(days, 1),
                "price": round(price) if price and price > 0 else None,
            }
        )
        models.add(model)
        conditions.add(tier)
        if color:
            colors.add(color)
        if storage:
            storages.add(int(storage))

    return {
        "records": records,
        "models": sorted(models),
        "colors": sorted(colors),
        "storages": sorted(storages),
        "conditions": sorted(conditions),
        "sampleSold": len(records),
        # Spariti esclusi perché probabilmente non venduti (scaduti/ritirati).
        "excluded": dict(excluded),
    }


def _resale_suggestions(
    db: Client, table: str, targets: dict[str, str]
) -> dict[str, dict[str, float]]:
    """Prezzo di rivendita suggerito (C7) dalla distribuzione dei prezzi attivi.

    Per modello: 'fastSalePrice' = 25° percentile (ti posizioni tra i più
    economici → vendita rapida), 'maxSalePrice' = mediana (prezzo pieno).
    """
    try:
        rows = _select_all(
            lambda: db.table(table)
            .select("target_id, variant_key, asking_price, condition_tier, title")
            .in_("status", list(_ACTIVE_STATUSES))
        )
    except Exception:
        return {}

    prices_by_model: dict[str, list[float]] = {}
    for row in rows:
        # Prezzo di rivendita = cosa chiedono gli altri per un telefono SANO:
        # rotti e accessori abbasserebbero il p25 a un prezzo irrealistico.
        if not is_healthy(row.get("condition_tier") or "buono"):
            continue
        if _is_accessory_listing(row.get("title")):
            continue
        model = _row_model(row, targets)
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


def _model_analytics(
    db: Client, table: str, targets: dict[str, str]
) -> dict[str, dict[str, Any]]:
    """Analitiche per modello dai listing ATTIVI (#6 Market Intelligence).

    Per modello: volume, box prezzi, margine potenziale (mediana↔p10), spread,
    affari attivi (proxy: <85% mediana), premio memoria, impatto condizione,
    venditori (distinti + finti privati) e distribuzione dell'analisi AI.
    """
    try:
        rows = _select_all(
            lambda: db.table(table)
            .select(
                _cols(
                    table, "target_id", "variant_key", "storage_gb", "condition_tier",
                    "asking_price", "seller_id", "seller_type", "ai_analysis",
                    "found_at", "title",
                )
            )
            .in_("status", list(_ACTIVE_STATUSES))
        )
    except Exception:
        return {}

    cutoff_7d = datetime.now(timezone.utc) - timedelta(days=7)

    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        if _is_accessory_listing(row.get("title")):
            continue
        model = _row_model(row, targets)
        if not model:
            continue
        d = agg.setdefault(
            model,
            {
                "all": [], "healthy": [], "byStorage": {}, "byCond": {},
                "sellers": set(), "fintoPrivato": 0, "inflow7d": 0,
                "ai": {"analyzed": 0, "legittimo": 0, "difetto": 0,
                       "sospetto": 0, "riparabili": 0},
            },
        )
        found = _born(row)
        if found and found >= cutoff_7d:
            d["inflow7d"] += 1
        price = _to_float(row.get("asking_price"))
        if price and price > 0:
            d["all"].append(price)
            tier = row.get("condition_tier") or "buono"
            d["byCond"].setdefault(tier, []).append(price)
            if is_healthy(tier):
                d["healthy"].append(price)
                st = row.get("storage_gb")
                if st:
                    d["byStorage"].setdefault(st, []).append(price)
        sid = row.get("seller_id")
        if sid:
            d["sellers"].add(sid)
        if row.get("seller_type") == "finto_privato":
            d["fintoPrivato"] += 1
        ai = row.get("ai_analysis")
        if isinstance(ai, dict):
            d["ai"]["analyzed"] += 1
            cat = ai.get("categoria_motivo")
            if cat in ("legittimo", "difetto", "sospetto"):
                d["ai"][cat] += 1
            if ai.get("riparabile"):
                d["ai"]["riparabili"] += 1

    out: dict[str, dict[str, Any]] = {}
    for model, d in agg.items():
        healthy = sorted(d["healthy"])
        box = None
        median = spread = margin_pct = None
        active_deals = 0
        if len(healthy) >= 4:
            q1, med, q3 = statistics.quantiles(healthy, n=4)
            p10 = statistics.quantiles(healthy, n=10)[0]
            median = med
            box = {
                "min": round(min(healthy)), "q1": round(q1), "median": round(med),
                "q3": round(q3), "max": round(max(healthy)),
            }
            spread = round(med - p10)
            margin_pct = round((med - p10) / med * 100, 1) if med else None
            active_deals = sum(1 for p in healthy if p < med * 0.85)
        elif healthy:
            median = statistics.median(healthy)

        out[model] = {
            "volume": len(d["all"]),
            "medianActive": round(median) if median else None,
            "priceBox": box,
            "marginPotentialPct": margin_pct,
            "spreadEur": spread,
            "activeDeals": active_deals,
            "storagePremium": {
                str(st): round(statistics.median(ps))
                for st, ps in sorted(d["byStorage"].items())
                if len(ps) >= 3
            },
            # F — Liquidità/volume per variante (taglio memoria): n. annunci
            # attivi sani per taglio = dove c'è offerta (e domanda) reale.
            "storageVolume": {
                str(st): len(ps)
                for st, ps in sorted(d["byStorage"].items())
            },
            "conditionImpact": {
                t: round(statistics.median(ps))
                for t, ps in d["byCond"].items()
                if len(ps) >= 3
            },
            "sellers": len(d["sellers"]),
            "fintoPrivato": d["fintoPrivato"],
            "inflow7d": d["inflow7d"],
            "ai": d["ai"],
        }
    return out


def _liquidity_index(
    sell_through: float | None,
    avg_days: float | None,
    demand_index: float | None,
    volume: int,
) -> tuple[int | None, str | None]:
    """F — Liquidità per variante: quanto in fretta gira e quanta domanda ha.

    Sintesi 0–100 di sell-through (% che sparisce = venduto), velocità di
    vendita (giorni), indice domanda/offerta 7gg. Restituisce (score, livello):
    ``alta`` gira in fretta, ``bassa`` = capitale che resta fermo. ``None`` se
    non ci sono ancora abbastanza dati (venduti) per stimarla."""
    parts: list[float] = []
    if sell_through is not None:
        parts.append(min(sell_through, 100.0))
    if avg_days is not None and avg_days > 0:
        # 3gg → ~100, 30gg → ~0 (oltre è illiquido).
        parts.append(max(0.0, min(100.0, (30 - avg_days) / 27 * 100)))
    if demand_index is not None:
        parts.append(min(100.0, demand_index * 50))  # indice 2.0 → 100
    if not parts:
        return None, None
    score = sum(parts) / len(parts)
    # Mercato troppo sottile (pochi annunci): il segnale è fragile, si sconta.
    if volume < 3:
        score *= 0.6
    score = round(score)
    level = "alta" if score >= 66 else "media" if score >= 33 else "bassa"
    return score, level


def get_market_intelligence(
    category: str,
    client: Client | None = None,
) -> dict[str, Any]:
    """KPIs, price trend series and per-model stats for a vertical."""
    db = client or get_db()
    target_cat = _target_category(category)
    products = _products_for_category(db, target_cat)

    # Annunci attivi: conteggio reale sulla tabella per-tipo (chiavata su target).
    table = _opportunities_table(category)
    try:
        active_listings = (
            db.table(table).select("id", count="exact").limit(1).execute().count or 0
        )
    except Exception:
        active_listings = 0

    # Statistiche dai VENDUTI (prezzo reale + giorni), prezzi dei listati attivi
    # e analitiche per modello (#6) dai listing attivi.
    targets = _targets_for_category(db, target_cat)
    sold_by_model, overall_tts = _sold_stats(db, table, targets)
    resale_by_model = _resale_suggestions(db, table, targets)
    analytics_by_model = _model_analytics(db, table, targets)

    # Trend storici per modello (curva di deprezzamento) da market_trends.
    trend_by_model: dict[str, dict[str, Any]] = {}
    if products:
        trend_rows = (
            db.table("market_trends")
            .select("product_id, trend_date, avg_price, volume")
            .in_("product_id", list(products))
            .order("trend_date", desc=False)
            .execute()
        ).data or []
        by_product: dict[str, list[dict[str, Any]]] = {}
        for row in trend_rows:
            by_product.setdefault(row["product_id"], []).append(row)
        for product_id, rows in by_product.items():
            name = products.get(product_id)
            if not name:
                continue
            rows_sorted = sorted(rows, key=lambda r: r["trend_date"])
            latest_avg = _to_float(rows_sorted[-1].get("avg_price"))
            change_pct = None
            if len(rows_sorted) >= 2 and latest_avg:
                prev_avg = _to_float(rows_sorted[0].get("avg_price"))
                if prev_avg:
                    change_pct = round((latest_avg - prev_avg) / prev_avg * 100, 1)
            trend_by_model[name] = {
                "avg": latest_avg,
                "changePct": change_pct,
                "series": [
                    {"date": r["trend_date"], "price": _to_float(r.get("avg_price"))}
                    for r in rows_sorted
                    if _to_float(r.get("avg_price")) is not None
                ],
            }

    # Unione di tutti i modelli visti: attivi ∪ venduti ∪ con storico.
    names = set(analytics_by_model) | set(sold_by_model) | set(trend_by_model)
    models: list[dict[str, Any]] = []
    for name in names:
        a = analytics_by_model.get(name) or {}
        sold = sold_by_model.get(name) or {}
        resale = resale_by_model.get(name) or {}
        t = trend_by_model.get(name) or {}

        volume = a.get("volume") or 0
        sample_sold = sold.get("sampleSold") or 0
        sell_through = (
            round(sample_sold / (sample_sold + volume) * 100, 1)
            if (sample_sold + volume) > 0
            else None
        )
        # Opportunity score = margine potenziale × fattore di liquidità.
        margin_pot = a.get("marginPotentialPct")
        opportunity = (
            round(margin_pot * (0.3 + (sell_through or 0) / 100), 1)
            if margin_pot is not None
            else None
        )
        # ROI per giorno di capitale = margine potenziale ÷ giorni di vendita:
        # il vero ordinamento del "cosa comprare" (resa/tempo). Giorni ONESTI
        # (Kaplan–Meier) quando disponibili, altrimenti media dei venduti.
        avg_days = sold.get("daysToSellKM") or sold.get("avgDaysToSell")
        roi_per_day = (
            round(margin_pot / avg_days, 2)
            if margin_pot is not None and avg_days and avg_days > 0
            else None
        )
        # Domanda/offerta: venduti vs nuovi immessi nell'ultima settimana.
        inflow7d = a.get("inflow7d") or 0
        outflow7d = sold.get("outflow7d") or 0
        demand_index = round(outflow7d / inflow7d, 2) if inflow7d > 0 else None

        # F — Liquidità per variante: quanto in fretta gira il capitale.
        liquidity_score, liquidity_level = _liquidity_index(
            sell_through, avg_days, demand_index, volume
        )

        models.append(
            {
                "name": name,
                "avg": t.get("avg"),
                "changePct": t.get("changePct"),
                "series": t.get("series") or [],
                "sample": volume or sample_sold,
                # A — analitiche dai listing attivi
                "volume": volume,
                "medianActive": a.get("medianActive"),
                "priceBox": a.get("priceBox"),
                "marginPotentialPct": margin_pot,
                "spreadEur": a.get("spreadEur"),
                "activeDeals": a.get("activeDeals") or 0,
                "storagePremium": a.get("storagePremium") or {},
                "storageVolume": a.get("storageVolume") or {},
                "conditionImpact": a.get("conditionImpact") or {},
                "sellers": a.get("sellers") or 0,
                "fintoPrivato": a.get("fintoPrivato") or 0,
                "ai": a.get("ai") or {},
                # C — vendite reali
                "avgDaysToSell": sold.get("avgDaysToSell"),
                "daysToSellKM": sold.get("daysToSellKM"),
                "sold7dPct": sold.get("sold7dPct"),
                "sold30dPct": sold.get("sold30dPct"),
                "removalKinds": sold.get("removalKinds") or {},
                "sampleSold": sold.get("sampleSold"),
                "soldMedian": sold.get("soldMedian"),
                "soldMax": sold.get("soldMax"),
                "priceBands": sold.get("priceBands") or [],
                "sellThroughRate": sell_through,
                # listati (fallback/confronto)
                "fastSalePrice": resale.get("fastSalePrice"),
                "maxSalePrice": resale.get("maxSalePrice"),
                # domanda/offerta (ultimi 7gg)
                "inflow7d": inflow7d,
                "outflow7d": outflow7d,
                "demandIndex": demand_index,
                # F — liquidità (quanto in fretta gira / quanta domanda)
                "liquidityScore": liquidity_score,
                "liquidityLevel": liquidity_level,
                # ranking
                "roiPerDayPct": roi_per_day,
                "opportunityScore": opportunity,
            }
        )

    # Ordina per ROI/giorno di capitale (resa reale/tempo); fallback su
    # opportunity score, poi volume — il "cosa comprare".
    models.sort(
        key=lambda m: (
            m.get("roiPerDayPct") or -1,
            m.get("opportunityScore") or -1,
            m.get("volume") or 0,
        ),
        reverse=True,
    )

    active_medians = [m["medianActive"] for m in models if m.get("medianActive")]
    avg_market_price = (
        round(sum(active_medians) / len(active_medians)) if active_medians else None
    )
    top_opportunity = (
        models[0]["name"] if models and models[0].get("opportunityScore") else None
    )

    # Chart: serie storica del primo modello (per opportunità) che ha uno storico.
    trend_series: list[dict[str, Any]] = []
    trend_product: str | None = None
    for m in models:
        if m.get("series"):
            trend_series = m["series"]
            trend_product = m["name"]
            break

    return {
        "activeListings": active_listings,
        "avgMarketPrice": avg_market_price,
        "outliersFiltered": None,
        "avgDaysToSell": overall_tts,
        "topOpportunity": top_opportunity,
        "trend": trend_series,
        "trendProduct": trend_product,
        "models": models,
        "sellers": _seller_ranking(db, table),
    }


def _seller_ranking(
    db: Client, table: str, limit: int = 25
) -> list[dict[str, Any]]:
    """Ranking globale venditori (intelligence): chi è più attivo e più motivato.

    Aggrega attivi + venduti per seller_id: quanti annunci ha, quanti ne vende e
    in quanti giorni, quanto ribassa. Un privato con molti annunci o che ribassa
    spesso è la priorità di contatto (leva di trattativa). Motivato = vende in
    fretta o ribassa spesso.
    """
    try:
        rows = _select_all(
            lambda: db.table(table)
            .select(
                _cols(table, "seller_id", "seller_type", "status", "asking_price",
                      "original_price", "found_at", "updated_at", "title")
            )
            .in_("status", list(_ACTIVE_STATUSES) + list(_SOLD_STATUSES))
        )
    except Exception:
        return []

    agg: dict[str, dict[str, Any]] = {}
    for row in rows:
        sid = row.get("seller_id")
        if not sid:
            continue
        d = agg.setdefault(
            sid,
            {"active": 0, "sold": 0, "days": [], "listed": 0, "drops": 0,
             "dropPcts": [], "type": row.get("seller_type"), "title": row.get("title")},
        )
        status = row.get("status")
        if status in _ACTIVE_STATUSES:
            d["active"] += 1
        elif status in _SOLD_STATUSES:
            d["sold"] += 1
            f = _born(row)
            u = _parse_ts(row.get("updated_at"))
            if f and u:
                days = (u - f).total_seconds() / 86400
                if 0 <= days <= 365:
                    d["days"].append(days)
        d["listed"] += 1
        orig = _to_float(row.get("original_price"))
        ask = _to_float(row.get("asking_price"))
        if orig and ask and orig > ask:
            d["drops"] += 1
            d["dropPcts"].append((orig - ask) / orig * 100)

    out: list[dict[str, Any]] = []
    for sid, d in agg.items():
        if d["active"] + d["sold"] < 2:  # solo venditori con un minimo di storia
            continue
        avg_days = round(statistics.fmean(d["days"]), 1) if d["days"] else None
        drop_rate = round(d["drops"] / d["listed"] * 100) if d["listed"] else 0
        out.append(
            {
                "sellerId": sid,
                "type": d["type"],
                "active": d["active"],
                "sold": d["sold"],
                "avgDaysToSell": avg_days,
                "dropRate": drop_rate,
                "avgDropPct": round(statistics.fmean(d["dropPcts"]), 1) if d["dropPcts"] else None,
                "motivated": bool((avg_days is not None and avg_days <= 14) or drop_rate >= 40),
                "sampleTitle": d["title"],
            }
        )

    # Motivati in cima, poi per volume totale (attivi + venduti).
    out.sort(key=lambda s: (s["motivated"], s["active"] + s["sold"]), reverse=True)
    return out[:limit]
