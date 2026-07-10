import asyncio
import logging
import statistics
from dataclasses import asdict
from datetime import date, datetime, timezone
from typing import Any

from supabase import Client

from backend.core.database import get_supabase_client
from backend.scrapers import ScrapedListing, SubitoScraper

logger = logging.getLogger(__name__)

# numeric(5,2) in market_trends.margin_pct caps the storable percentage.
MARGIN_PCT_LIMIT = 999.99


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


def save_live_opportunities(
    product_id: str,
    listings: list[ScrapedListing],
    target_id: str | None = None,
    client: Client | None = None,
) -> list[dict[str, Any]]:
    if not listings:
        return []

    db = client or get_supabase_client()
    existing_urls = get_existing_listing_urls(
        db,
        [listing.url for listing in listings],
    )
    # Market average is isolated per target: a BMW 120d Gen 1 uses only the
    # Gen 1 target's average, never a generic "BMW 120d" one.
    market_avg = get_latest_market_avg(db, target_id) if target_id else None

    payloads = [
        {
            "product_id": product_id,
            "target_id": target_id,
            "listing_url": listing.url,
            "title": listing.title,
            "location": listing.location,
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


def get_latest_market_avg(client: Client, target_id: str) -> float | None:
    """Latest market average for a specific target (strict per-target isolation)."""
    result = (
        client.table("market_trends")
        .select("avg_price")
        .eq("target_id", target_id)
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


# Un blocco = una pagina API (~50 annunci restituiti istantaneamente).
SNIPER_BLOCK_SIZE = 50


async def scrape_subito_and_save(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    pages: int = 1,
    strict_filters: dict[str, Any] | None = None,
    target_id: str | None = None,
) -> dict[str, Any]:
    """Cecchino Live ottimizzato: processa in blocco 'pages' pagine dell'API.

    1) Fetch veloce del blocco via proxy (nessuna immagine, filtri applicati).
    2) Dedup contro il DB → tiene solo gli annunci nuovi.
    3) Download immagini SOLO dei nuovi, dalla CDN diretta (budget proxy salvo).
    4) Calcolo margini e salvataggio.
    """
    scraper = SubitoScraper()
    max_results = max(1, pages) * SNIPER_BLOCK_SIZE

    # 1) Blocco di annunci dall'API (con strict_filters già applicati in-blocco).
    #    max_pages=pages: esattamente 'pages' richieste al proxy, niente over-fetch.
    #    Con strict_filters (auto) la precisione la danno i filtri nativi, non il
    #    match del titolo: es. "Golf GTI" non deve filtrare per token del titolo.
    #    strict_filters vuoti ({}) o None → smartphone → match preciso del modello.
    listings = await scraper.search_text(
        query=query,
        max_results=max_results,
        strict_match=not strict_filters,
        filters=strict_filters,
        max_pages=pages,
    )

    specs = {"strict_filters": strict_filters} if strict_filters else None
    product, product_created = await asyncio.to_thread(
        get_or_create_product, query, category, specs
    )
    product_id = str(product["id"])

    # 2) Deduplica contro il DB PRIMA di scaricare le immagini.
    db = get_supabase_client()
    existing_urls = await asyncio.to_thread(
        get_existing_listing_urls, db, [listing.url for listing in listings]
    )
    new_listings = [listing for listing in listings if listing.url not in existing_urls]

    # 3) Download immagini solo per i nuovi (CDN diretta, concorrente).
    new_listings = await scraper.store_images(new_listings)

    # 4) Margini (media isolata per target) + salvataggio con target_id.
    saved = await asyncio.to_thread(
        save_live_opportunities, product_id, new_listings, target_id
    )

    return {
        "query": query,
        "category": category,
        "pages": pages,
        "product": product,
        "product_created": product_created,
        "scraped_count": len(listings),
        "new_count": len(new_listings),
        "saved_count": len(saved),
        "listings": [asdict(listing) for listing in new_listings],
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
    listings = await scraper.search_text(
        query=query,
        max_results=max_results,
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
