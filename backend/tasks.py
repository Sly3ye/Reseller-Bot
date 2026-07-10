import asyncio
import logging
import statistics
import uuid
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from backend.core.database import get_supabase_client
from backend.scrapers import ScrapedListing, SubitoScraper

logger = logging.getLogger(__name__)

def anti_spam_bounds(category: str) -> tuple[int, int | None]:
    """Local anti-spam price bounds (min, max) by category.

    Drops absurd listings before dedup/margins/save: cars outside 1k–200k,
    phones under 50 EUR (spare parts, accessories, scam bait, wrong price).
    """
    if category == "automobile":
        return 1000, 200000
    return 50, None


def get_or_create_product(
    name: str,
    category: str,
    specs: dict[str, Any] | None = None,
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

    payload: dict[str, Any] = {
        "model": name,
        "category": category,
        "brand": infer_brand(name),
    }
    if specs:
        payload["specs"] = specs

    created = db.table("products").insert(payload).execute()
    if not created.data:
        raise RuntimeError("Supabase did not return the created product.")

    return created.data[0], True


def infer_brand(model: str) -> str:
    normalized = model.strip().lower()
    if "iphone" in normalized or "ipad" in normalized:
        return "Apple"

    return model.strip().split()[0].title() if model.strip() else "Unknown"


# Un blocco = una pagina API (~50 annunci restituiti istantaneamente).
SNIPER_BLOCK_SIZE = 50


def opportunities_table(category: str) -> str:
    """Routing: 'automobile' → _auto, tutto il resto (smartphone/tech) → _tech."""
    return (
        "live_opportunities_auto"
        if category == "automobile"
        else "live_opportunities_tech"
    )


def get_existing_opportunities(
    client: Client, table: str, urls: list[str]
) -> dict[str, dict[str, Any]]:
    """Map listing_url → {id, asking_price} per le righe già presenti in `table`."""
    if not urls:
        return {}
    rows = (
        client.table(table)
        .select("id, listing_url, asking_price")
        .in_("listing_url", urls)
        .execute()
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows.data or []:
        price = row.get("asking_price")
        result[row["listing_url"]] = {
            "id": row["id"],
            "asking_price": float(price) if price is not None else None,
        }
    return result


def _opportunity_payload(
    category: str, target_id: str | None, listing: ScrapedListing, now: str
) -> dict[str, Any]:
    # id e found_at/updated_at non hanno DEFAULT nel DDL → li forniamo noi.
    meta = listing.metadata or {}
    payload: dict[str, Any] = {
        "id": str(uuid.uuid4()),
        "target_id": target_id,
        "listing_url": listing.url,
        "title": listing.title,
        "description": listing.description,
        "asking_price": listing.price_amount,
        "original_price": None,
        "location": listing.location,
        "image_urls": listing.image_urls,
        "status": "nuovo",
        "found_at": now,
        "updated_at": now,
    }
    if category == "automobile":
        payload.update(
            {
                "year": meta.get("year"),
                "km": meta.get("km"),
                "transmission": meta.get("transmission"),
                "fuel": meta.get("fuel"),
            }
        )
    return payload


def insert_opportunities(
    client: Client,
    table: str,
    category: str,
    target_id: str | None,
    listings: list[ScrapedListing],
) -> list[dict[str, Any]]:
    """Inserisce opportunità nuove (asking_price è NOT NULL → serve il prezzo)."""
    now = datetime.now(timezone.utc).isoformat()
    payloads = [
        _opportunity_payload(category, target_id, listing, now)
        for listing in listings
        if listing.price_amount is not None
    ]
    if not payloads:
        return []
    inserted = client.table(table).insert(payloads).execute()
    return inserted.data or []


def apply_price_updates(
    client: Client,
    table: str,
    existing: dict[str, dict[str, Any]],
    listings: list[ScrapedListing],
) -> dict[str, int]:
    """Annunci già presenti: aggiorna updated_at; su CALO di prezzo salva lo
    storico in price_history e sposta il vecchio prezzo in original_price."""
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    price_drops = 0
    history_rows: list[dict[str, Any]] = []

    for listing in listings:
        row = existing.get(listing.url)
        if not row:
            continue
        listing_id = row["id"]
        old_price = row["asking_price"]
        new_price = listing.price_amount

        patch: dict[str, Any] = {"updated_at": now}
        if new_price is not None and old_price is not None and new_price < old_price:
            patch["asking_price"] = new_price
            patch["original_price"] = old_price
            history_rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "old_price": old_price,
                    "new_price": new_price,
                }
            )
            price_drops += 1

        client.table(table).update(patch).eq("id", listing_id).execute()
        updated += 1

    if history_rows:
        client.table("price_history").insert(history_rows).execute()

    return {"updated": updated, "price_drops": price_drops}


async def persist_opportunities(
    scraper: SubitoScraper,
    category: str,
    target_id: str | None,
    listings: list[ScrapedListing],
    download_images: bool = True,
) -> dict[str, int]:
    """Routing + UPSERT condiviso da Sniper e Backfill.

    Instrada sulla tabella per categoria, deduplica su listing_url, scarica le
    immagini SOLO per i nuovi (se richiesto) e li inserisce; per gli esistenti
    aggiorna updated_at e gestisce i cali di prezzo (price_history).
    """
    if not listings:
        return {"new": 0, "updated": 0, "price_drops": 0}

    table = opportunities_table(category)
    db = get_supabase_client()
    existing = await asyncio.to_thread(
        get_existing_opportunities, db, table, [listing.url for listing in listings]
    )

    new_listings = [listing for listing in listings if listing.url not in existing]
    dup_listings = [listing for listing in listings if listing.url in existing]

    if download_images and new_listings:
        new_listings = await scraper.store_images(new_listings)

    inserted = await asyncio.to_thread(
        insert_opportunities, db, table, category, target_id, new_listings
    )
    updates = await asyncio.to_thread(
        apply_price_updates, db, table, existing, dup_listings
    )

    return {
        "new": len(inserted),
        "updated": updates["updated"],
        "price_drops": updates["price_drops"],
    }


async def scrape_subito_and_save(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    pages: int = 1,
    strict_filters: dict[str, Any] | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Cecchino Live: processa in blocco 'pages' pagine dell'API con routing/UPSERT.

    1) Fetch del blocco via proxy (filtri nativi + anti-spam applicati).
    2) Routing su _auto/_tech, dedup su listing_url.
    3) Immagini SOLO per i nuovi (CDN diretta) + insert; esistenti → updated_at
       e price_history sui cali di prezzo.
    """
    scraper = SubitoScraper()
    max_results = max(1, pages) * SNIPER_BLOCK_SIZE
    anti_min, anti_max = anti_spam_bounds(category)

    listings = await scraper.search_text(
        query=query,
        max_results=max_results,
        min_price=anti_min,
        max_price=anti_max,
        strict_match=not strict_filters,
        filters=strict_filters,
        max_pages=pages,
    )

    result = await persist_opportunities(
        scraper, category, target_id, listings, download_images=True
    )

    return {
        "query": query,
        "category": category,
        "pages": pages,
        "target_id": target_id,
        "table": opportunities_table(category),
        "scraped_count": len(listings),
        "new_count": result["new"],
        "updated_count": result["updated"],
        "price_drops": result["price_drops"],
        "saved_count": result["new"],
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
    target_id: str | None,
    product_id: str,
    stats: dict[str, float | int],
    client: Client | None = None,
) -> dict[str, Any] | None:
    """Upsert today's market snapshot for a target (one row per target/day)."""
    db = client or get_supabase_client()
    payload = {
        "target_id": target_id,
        "product_id": product_id,
        "trend_date": date.today().isoformat(),
        **stats,
    }
    result = (
        db.table("market_trends")
        .upsert(payload, on_conflict="target_id,trend_date")
        .execute()
    )
    return result.data[0] if result.data else None


async def run_nightly_batch(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    max_results: int = 50,
    strict_filters: dict[str, Any] | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Motore Notturno per UN target: media/IQR isolati per target_id.

    Applica gli strict_filters del target durante lo scraping, così la media
    è calcolata SOLO sugli annunci di quella generazione/variante specifica.
    """
    scraper = SubitoScraper()
    anti_min, anti_max = anti_spam_bounds(category)
    listings = await scraper.search_text(
        query=query,
        max_results=max_results,
        min_price=anti_min,
        max_price=anti_max,
        strict_match=not strict_filters,
        filters=strict_filters,
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
            save_market_trend, target_id, str(product["id"]), stats
        )

    return {
        "mode": "nightly_batch",
        "query": query,
        "category": category,
        "target_id": target_id,
        "product_id": str(product["id"]),
        "product_created": product_created,
        "scraped_count": len(listings),
        "prices_considered": len(prices),
        "stats": stats,
        "trend": trend,
    }


async def run_nightly_batch_all_products() -> dict[str, Any]:
    """Motore Notturno (scheduled): refresh market trends per TARGET.

    Itera target_models (non i prodotti): la media/IQR è calcolata e salvata
    per target_id usando i suoi strict_filters, così ogni generazione/variante
    ha la propria statistica isolata.
    """
    try:
        targets = await asyncio.to_thread(get_active_targets)
    except Exception:
        logger.exception("Nightly batch: could not fetch target_models")
        return {"mode": "nightly_batch_all", "targets": 0, "results": [], "error": True}
    logger.info("Nightly batch: %d active target(s)", len(targets))

    results: list[dict[str, Any]] = []
    for target in targets:
        query = target["query"]
        try:
            outcome = await run_nightly_batch(
                query=query,
                category=target["category"],
                strict_filters=target.get("strict_filters") or None,
                target_id=target["id"],
            )
            results.append(outcome)
            logger.info(
                "Nightly batch done for target '%s' (volume=%s)",
                query,
                (outcome.get("stats") or {}).get("volume"),
            )
        except Exception:
            logger.exception("Nightly batch failed for target '%s'", query)
            results.append({"query": query, "error": True})

    return {"mode": "nightly_batch_all", "targets": len(targets), "results": results}


def get_active_targets(
    category: str | None = None,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    """Fetch the scraping fleet from target_models (is_active = true).

    Pass ``category`` to scope to one vertical (e.g. the automobile sniper).
    """
    db = client or get_supabase_client()
    query = (
        db.table("target_models")
        .select("id, category, query, strict_filters")
        .eq("is_active", True)
    )
    if category:
        query = query.eq("category", category)
    return query.execute().data or []


def update_target_last_scanned(
    target_id: str, client: Client | None = None
) -> None:
    db = client or get_supabase_client()
    db.table("target_models").update(
        {"last_scanned": datetime.now(timezone.utc).isoformat()}
    ).eq("id", target_id).execute()


async def run_sniper_all_products(
    category: str | None = None,
    pages: int = 1,
) -> dict[str, Any]:
    """Cecchino Live (scheduled): hunt fresh opportunities for every active target.

    Reads the scraping fleet from ``target_models`` (DB-driven, non hardcoded),
    processes ``pages`` API blocks per target applying its ``strict_filters``,
    then stamps ``last_scanned``. ``category`` scopes to one vertical.
    """
    try:
        targets = await asyncio.to_thread(get_active_targets, category)
    except Exception:
        logger.exception("Sniper live: could not fetch target_models")
        return {"mode": "sniper_targets", "targets": 0, "results": [], "error": True}
    logger.info(
        "Sniper live (%s): %d active target(s)", category or "all", len(targets)
    )

    results: list[dict[str, Any]] = []
    for target in targets:
        query = target["query"]
        target_category = target["category"]
        strict_filters = target.get("strict_filters") or None
        try:
            outcome = await scrape_subito_and_save(
                query=query,
                category=target_category,
                pages=pages,
                strict_filters=strict_filters,
                target_id=target["id"],
            )
            await asyncio.to_thread(update_target_last_scanned, target["id"])
            results.append(
                {
                    "query": query,
                    "category": target_category,
                    "scraped_count": outcome["scraped_count"],
                    "new_count": outcome["new_count"],
                    "saved_count": outcome["saved_count"],
                }
            )
            logger.info(
                "Sniper done for '%s' (block=%d, new opportunities=%d)",
                query,
                outcome["scraped_count"],
                outcome["saved_count"],
            )
        except Exception:
            logger.exception("Sniper failed for '%s'", query)
            results.append({"query": query, "error": True})

    return {
        "mode": "sniper_targets",
        "category": category,
        "targets": len(targets),
        "results": results,
    }


if __name__ == "__main__":
    print(asyncio.run(scrape_subito_and_save()))
