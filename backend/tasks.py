import asyncio
from dataclasses import asdict
from typing import Any

from supabase import Client

from backend.core.database import get_supabase_client
from backend.scrapers import ScrapedListing, SearchRequest, SubitoScraper


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
    payloads = [
        {
            "product_id": product_id,
            "listing_url": listing.url,
            "asking_price": listing.price_amount,
            "source": listing.source,
        }
        for listing in listings
        if listing.url not in existing_urls
    ]
    if not payloads:
        return []

    inserted = db.table("live_opportunities").insert(payloads).execute()
    return inserted.data or []


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


async def scrape_subito_and_save(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    max_results: int = 5,
) -> dict[str, Any]:
    scraper = SubitoScraper(headless=True, organic_only=True)
    listings = await scraper.search_text(query=query, max_results=max_results)

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


async def run_nightly_batch() -> dict[str, int | str]:
    """Simulate broad historical extraction across target search terms."""
    queries = ["fiat panda", "iphone 15", "bmw serie 1"]
    scraper = SubitoScraper(headless=True)
    total_results = 0

    for query in queries:
        results = await scraper.search(SearchRequest(query=query, max_results=25))
        total_results += len(results)

    return {"mode": "nightly_batch", "queries": len(queries), "results": total_results}


async def run_sniper_live() -> dict[str, int | str]:
    """Simulate fast underpriced-deal discovery for a focused search."""
    scraper = SubitoScraper(headless=True)
    results = await scraper.search(
        SearchRequest(query="iphone 15 pro", max_results=10, max_price=650)
    )

    return {"mode": "sniper_live", "results": len(results)}


if __name__ == "__main__":
    print(asyncio.run(scrape_subito_and_save()))
