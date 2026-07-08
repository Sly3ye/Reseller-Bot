import asyncio

from backend.scrapers import SearchRequest, SubitoScraper


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
    print(asyncio.run(run_sniper_live()))
