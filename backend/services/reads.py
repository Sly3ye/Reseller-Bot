"""Read-side queries that feed the frontend (Live Sniper + Market Intelligence)."""

from __future__ import annotations

import re
from typing import Any
from urllib.parse import urlparse

from supabase import Client

from backend.core.database import get_supabase_client

_LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")


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


def _shape_opportunity(row: dict[str, Any], model: str | None) -> dict[str, Any]:
    return {
        "id": row["id"],
        "title": row.get("title") or _title_from_url(row.get("listing_url")) or model,
        "location": row.get("location"),
        "askingPrice": _to_float(row.get("asking_price")),
        "marketAvg": _to_float(row.get("market_avg_price")),
        "marginEur": _to_float(row.get("estimated_margin")),
        "marginPct": _to_float(row.get("margin_pct")),
        "description": row.get("description"),
        "images": row.get("image_urls") or [],
        "foundAt": row.get("found_at"),
        "source": row.get("source"),
        "status": row.get("status"),
        "url": row.get("listing_url"),
    }


def list_opportunities(
    category: str,
    limit: int = 60,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """Live Sniper feed: opportunities for a vertical, newest first."""
    db = client or get_supabase_client()
    products = _products_for_category(db, category)
    if not products:
        return []

    rows = (
        db.table("live_opportunities")
        .select("*")
        .in_("product_id", list(products))
        .order("found_at", desc=True)
        .limit(limit)
        .execute()
    )
    return [
        _shape_opportunity(row, products.get(row.get("product_id")))
        for row in rows.data or []
    ]


def get_market_intelligence(
    category: str,
    client: Client | None = None,
) -> dict[str, Any]:
    """KPIs, price trend series and per-model stats for a vertical."""
    db = client or get_supabase_client()
    products = _products_for_category(db, category)

    empty = {
        "activeListings": 0,
        "avgMarketPrice": None,
        "outliersFiltered": None,
        "trend": [],
        "trendProduct": None,
        "models": [],
    }
    if not products:
        return empty

    product_ids = list(products)

    opportunities = (
        db.table("live_opportunities")
        .select("market_avg_price")
        .in_("product_id", product_ids)
        .execute()
    )
    opp_rows = opportunities.data or []
    active_listings = len(opp_rows)
    market_avgs = [
        v for v in (_to_float(r.get("market_avg_price")) for r in opp_rows) if v is not None
    ]
    avg_market_price = round(sum(market_avgs) / len(market_avgs), 2) if market_avgs else None

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
    for product_id, rows in by_product.items():
        rows_sorted = sorted(rows, key=lambda r: r["trend_date"])
        latest = rows_sorted[-1]
        latest_avg = _to_float(latest.get("avg_price"))
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
