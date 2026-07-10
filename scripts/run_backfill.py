"""Deep Backfill massivo — l'aspirapolvere.

Per ogni target attivo in target_models, cicla in profondità la paginazione
dell'API di Subito (start=0, 50, 100, …) via proxy residenziale + retry tenacity,
applica gli strict_filters e l'anti-spam, e usa l'ESATTA logica di routing/UPSERT
del Cecchino (persist_opportunities → _auto/_tech + price_history sui cali).

Non scarica immagini (volume enorme): le riempirà lo Sniper sui nuovi.

Esegui dalla root:
  python scripts/run_backfill.py [max_pages_per_target] [category]
  es. python scripts/run_backfill.py 10 automobile
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scrapers.subito import SubitoScraper  # noqa: E402
from backend.tasks import (  # noqa: E402
    anti_spam_bounds,
    get_active_targets,
    persist_opportunities,
)

BACKFILL_PAGE_SIZE = 50   # annunci per richiesta all'API
DEFAULT_MAX_PAGES = 10    # profondità per target (override via argv[1])


async def backfill_target(
    scraper: SubitoScraper, target: dict, max_pages: int
) -> dict[str, int]:
    query = target["query"]
    category = target["category"]
    filters = target.get("strict_filters") or None
    anti_min, anti_max = anti_spam_bounds(category)

    totals = {"scraped": 0, "new": 0, "updated": 0, "price_drops": 0}

    async with scraper._make_api_client() as api_client:
        start = 0
        count_all: int | None = None
        for _ in range(max_pages):
            params = {
                "q": query,
                "t": "s",
                "lim": str(BACKFILL_PAGE_SIZE),
                "start": str(start),
            }
            response = await scraper._get_with_retry(api_client, scraper.HADES_URL, params)
            payload = response.json()
            ads = payload.get("ads") or []
            if not ads:
                break
            if count_all is None:
                count_all = payload.get("count_all") or 0

            # Parsing + strict_filters + anti-spam (stessa logica del blocco Sniper).
            listings = []
            for ad in ads:
                if filters and not scraper._passes_filters(ad, filters):
                    continue
                listing = scraper._parse_ad(ad)
                if listing is None:
                    continue
                if not scraper._within_price(listing.price_amount, anti_min, anti_max):
                    continue
                listings.append(listing)

            # Routing + UPSERT identico al Cecchino (senza immagini).
            result = await persist_opportunities(
                scraper, category, target["id"], listings, download_images=False
            )
            totals["scraped"] += len(listings)
            totals["new"] += result["new"]
            totals["updated"] += result["updated"]
            totals["price_drops"] += result["price_drops"]

            print(
                f"    start={start:<5} → {len(listings):>2} pertinenti | "
                f"+{result['new']} nuovi, {result['updated']} agg, "
                f"{result['price_drops']} cali prezzo"
            )

            start += BACKFILL_PAGE_SIZE
            if count_all and start >= count_all:
                break

    return totals


async def main() -> None:
    max_pages = int(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_MAX_PAGES
    category = sys.argv[2] if len(sys.argv) > 2 else None

    scraper = SubitoScraper()
    targets = await asyncio.to_thread(get_active_targets, category)
    scope = f"categoria '{category}'" if category else "tutte le categorie"
    print(f"Deep Backfill: {len(targets)} target attivi ({scope}), max {max_pages} pagine/target")

    grand = {"scraped": 0, "new": 0, "updated": 0, "price_drops": 0}
    for target in targets:
        print(f"\nTARGET: {target['query']} ({target['category']})")
        try:
            totals = await backfill_target(scraper, target, max_pages)
        except Exception as exc:
            print(f"  ERRORE su '{target['query']}': {type(exc).__name__}: {exc}")
            continue
        print(
            f"  → totale: scraped {totals['scraped']}, new {totals['new']}, "
            f"updated {totals['updated']}, price_drops {totals['price_drops']}"
        )
        for k in grand:
            grand[k] += totals[k]

    print(
        f"\n=== BACKFILL COMPLETATO === scraped {grand['scraped']}, "
        f"new {grand['new']}, updated {grand['updated']}, price_drops {grand['price_drops']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
