"""Read-side queries that feed the frontend (Live Sniper + Market Intelligence).

Routing table-per-type: le opportunità vivono in ``live_opportunities_auto``
(categoria 'automobile') o ``live_opportunities_tech`` (smartphone/tech), sono
chiavate su ``target_id`` (→ ``target_models.query`` = nome modello) e i cali di
prezzo sono storicizzati in ``price_history`` (listing_id = id opportunità).
"""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from supabase import Client

from backend.core.database import get_supabase_client

_LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")

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


def _market_avg_by_model(db: Client, category: str) -> dict[str, float]:
    """Ultima media di mercato (market_trends) per nome modello.

    market_trends è chiavata su product_id: passiamo per products per risalire
    al nome modello, poi teniamo la media dello snapshot più recente.
    """
    products = _products_for_category(db, category)  # id → model
    if not products:
        return {}

    trends = (
        db.table("market_trends")
        .select("product_id, trend_date, avg_price")
        .in_("product_id", list(products))
        .order("trend_date", desc=True)
        .execute()
    )
    avg_by_model: dict[str, float] = {}
    for row in trends.data or []:
        model = products.get(row["product_id"])
        avg = _to_float(row.get("avg_price"))
        # order desc → la prima occorrenza per modello è la più recente.
        if model and avg is not None and model not in avg_by_model:
            avg_by_model[model] = avg
    return avg_by_model


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
        "source": "Subito",
        "status": row.get("status"),
        "url": row.get("listing_url"),
    }


def list_opportunities(
    category: str,
    limit: int = 60,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """Live Sniper feed: opportunità di una categoria, dalle più recenti.

    Instrada sulla tabella per-tipo, risolve il nome modello via target_id,
    arricchisce con la media di mercato (margini) e i cali di prezzo storici.
    """
    db = client or get_supabase_client()
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
    market_avg = _market_avg_by_model(db, target_cat)  # model name → avg
    price_history = _latest_price_history(db, [row["id"] for row in rows])

    result = []
    for row in rows:
        model = targets.get(row.get("target_id"))
        result.append(
            _shape_opportunity(
                row,
                model,
                market_avg.get(model) if model else None,
                price_history.get(row["id"]),
            )
        )
    return result


def get_market_intelligence(
    category: str,
    client: Client | None = None,
) -> dict[str, Any]:
    """KPIs, price trend series and per-model stats for a vertical."""
    db = client or get_supabase_client()
    target_cat = _target_category(category)
    products = _products_for_category(db, target_cat)

    empty = {
        "activeListings": 0,
        "avgMarketPrice": None,
        "outliersFiltered": None,
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

    if not products:
        return {**empty, "activeListings": active_listings}

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
        models.append(
            {
                "name": products.get(product_id, "—"),
                "avg": latest_avg,
                "sample": latest.get("volume"),
                "changePct": change_pct,
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
        "trend": trend_series,
        "trendProduct": trend_product,
        "models": models,
    }
