import asyncio
import statistics
import sys
from dataclasses import asdict
from datetime import date
from typing import Any

from supabase import Client

from backend.core.database import get_supabase_client
from backend.scrapers import ScrapedListing, SearchRequest, SubitoScraper

# numeric(5,2) in market_trends.margin_pct caps the storable percentage.
MARGIN_PCT_LIMIT = 999.99


def get_or_create_product(
    name: str,
    category: str,
    client: Client | None = None,
) -> tuple[dict[str, Any], bool]:
    db = client or get_supabase_client()

    existing = (
        db.table("products")
        .select("*")
        .eq("model", name)
        .eq("category", category)
        .limit(1)
        .execute()
    )
    if existing.data:
        return existing.data[0], False

    created = (
        db.table("products")
        .insert({"model": name, "category": category, "brand": infer_brand(name)})
        .execute()
    )
    if not created.data:
        raise RuntimeError("Supabase did not return the created product.")

    return created.data[0], True


def save_live_opportunities(
    product_id: str,
    listings: list[ScrapedListing],
    client: Client | None = None,
) -> list[dict[str, Any]]:
    if not listings:
        return []

    db = client or get_supabase_client()
    existing_urls = get_existing_listing_urls(
        db,
        [listing.url for listing in listings],
    )
    # Latest market average for this product feeds the margin computation.
    market_avg = get_latest_market_avg(db, product_id)

    payloads = [
        {
            "product_id": product_id,
            "listing_url": listing.url,
            "asking_price": listing.price_amount,
            "source": listing.source,
            "description": listing.description,
            "image_urls": listing.image_urls,
            **compute_margin(market_avg, listing.price_amount),
        }
        for listing in listings
        if listing.url not in existing_urls
    ]
    if not payloads:
        return []

    inserted = db.table("live_opportunities").insert(payloads).execute()
    return inserted.data or []


def get_latest_market_avg(client: Client, product_id: str) -> float | None:
    result = (
        client.table("market_trends")
        .select("avg_price")
        .eq("product_id", product_id)
        .order("trend_date", desc=True)
        .limit(1)
        .execute()
    )
    if result.data and result.data[0].get("avg_price") is not None:
        return float(result.data[0]["avg_price"])
    return None


def compute_margin(
    market_avg: float | None,
    asking_price: float | None,
) -> dict[str, float | None]:
    """Margin of a deal vs. the current market average.

    estimated_margin = market_avg - asking; margin_pct is that as a % of the
    market average (positive = underpriced = good deal). Clamped to the
    numeric(5,2) range so extreme outliers never break the insert.
    """
    if market_avg is None or asking_price is None:
        return {
            "market_avg_price": market_avg,
            "estimated_margin": None,
            "margin_pct": None,
        }

    estimated_margin = round(market_avg - asking_price, 2)
    margin_pct: float | None = None
    if market_avg:
        margin_pct = round(estimated_margin / market_avg * 100, 2)
        margin_pct = max(-MARGIN_PCT_LIMIT, min(MARGIN_PCT_LIMIT, margin_pct))

    return {
        "market_avg_price": round(market_avg, 2),
        "estimated_margin": estimated_margin,
        "margin_pct": margin_pct,
    }


def get_existing_listing_urls(client: Client, urls: list[str]) -> set[str]:
    if not urls:
        return set()

    existing = (
        client.table("live_opportunities")
        .select("listing_url")
        .in_("listing_url", urls)
        .execute()
    )
    return {row["listing_url"] for row in existing.data or []}


def infer_brand(model: str) -> str:
    normalized = model.strip().lower()
    if "iphone" in normalized or "ipad" in normalized:
        return "Apple"

    return model.strip().split()[0].title() if model.strip() else "Unknown"


def _run_scrape_in_dedicated_loop(coro_factory) -> list[ScrapedListing]:
    """Run an async scrape on a fresh event loop that supports subprocesses.

    On Windows, uvicorn's ``--reload`` forces a ``SelectorEventLoop``, which
    cannot spawn subprocesses. Playwright needs one to launch the browser, so
    we run the coroutine on a dedicated ``ProactorEventLoop`` here instead.
    Meant to be called from a worker thread (e.g. via ``asyncio.to_thread``)
    so it never conflicts with the loop uvicorn is already running.
    """
    if sys.platform == "win32":
        loop = asyncio.ProactorEventLoop()
    else:
        loop = asyncio.new_event_loop()

    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(coro_factory())
    finally:
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            loop.close()


async def scrape_subito_and_save(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    max_results: int = 5,
) -> dict[str, Any]:
    scraper = SubitoScraper(headless=True, organic_only=True)
    listings = await asyncio.to_thread(
        _run_scrape_in_dedicated_loop,
        lambda: scraper.search_text(query=query, max_results=max_results, deep=True),
    )

    product, product_created = await asyncio.to_thread(
        get_or_create_product,
        query,
        category,
    )
    saved = await asyncio.to_thread(
        save_live_opportunities,
        str(product["id"]),
        listings,
    )

    return {
        "query": query,
        "category": category,
        "product": product,
        "product_created": product_created,
        "scraped_count": len(listings),
        "saved_count": len(saved),
        "listings": [asdict(listing) for listing in listings],
        "saved": saved,
    }


def filter_price_outliers(prices: list[float]) -> list[float]:
    """Drop anomalous prices with the 1.5*IQR rule (needs >= 4 samples)."""
    values = sorted(float(p) for p in prices if isinstance(p, (int, float)) and p > 0)
    if len(values) < 4:
        return values

    q1, _, q3 = statistics.quantiles(values, n=4)
    iqr = q3 - q1
    if iqr <= 0:
        return values

    low = q1 - 1.5 * iqr
    high = q3 + 1.5 * iqr
    return [v for v in values if low <= v <= high]


def compute_market_stats(prices: list[float]) -> dict[str, float | int] | None:
    """Clean the prices and reduce them to the market snapshot metrics."""
    cleaned = filter_price_outliers(prices)
    if not cleaned:
        return None

    return {
        "avg_price": round(statistics.fmean(cleaned), 2),
        "min_price": round(min(cleaned), 2),
        "max_price": round(max(cleaned), 2),
        "volume": len(cleaned),
    }


def save_market_trend(
    product_id: str,
    stats: dict[str, float | int],
    client: Client | None = None,
) -> dict[str, Any] | None:
    """Upsert today's market snapshot for a product (one row per day)."""
    db = client or get_supabase_client()
    payload = {
        "product_id": product_id,
        "trend_date": date.today().isoformat(),
        **stats,
    }
    result = (
        db.table("market_trends")
        .upsert(payload, on_conflict="product_id,trend_date")
        .execute()
    )
    return result.data[0] if result.data else None


async def run_nightly_batch(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    max_results: int = 50,
) -> dict[str, Any]:
    """Motore Notturno: light-scrape a product, clean prices, store the trend.

    Light mode only reads the search results page (no per-listing deep scrape),
    so it is fast enough to sweep many prices and compute a market average.
    """
    scraper = SubitoScraper(headless=True, organic_only=True)
    listings = await asyncio.to_thread(
        _run_scrape_in_dedicated_loop,
        lambda: scraper.search_text(
            query=query,
            max_results=max_results,
            deep=False,
            strict_match=False,
            pages=3,
        ),
    )

    prices = [
        float(listing.price_amount)
        for listing in listings
        if listing.price_amount is not None
    ]
    stats = compute_market_stats(prices)

    product, product_created = await asyncio.to_thread(
        get_or_create_product, query, category
    )

    trend = None
    if stats is not None:
        trend = await asyncio.to_thread(
            save_market_trend, str(product["id"]), stats
        )

    return {
        "mode": "nightly_batch",
        "query": query,
        "category": category,
        "product_id": str(product["id"]),
        "product_created": product_created,
        "scraped_count": len(listings),
        "prices_considered": len(prices),
        "stats": stats,
        "trend": trend,
    }


async def run_sniper_live() -> dict[str, int | str]:
    """Simulate fast underpriced-deal discovery for a focused search."""
    scraper = SubitoScraper(headless=True)
    results = await scraper.search(
        SearchRequest(query="iphone 15 pro", max_results=10, max_price=650)
    )

    return {"mode": "sniper_live", "results": len(results)}


if __name__ == "__main__":
    print(asyncio.run(scrape_subito_and_save()))
