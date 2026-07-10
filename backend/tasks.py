import asyncio
import logging
import re
import statistics
import uuid
from collections import Counter
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
        .select("id, listing_url, asking_price, image_urls")
        .in_("listing_url", urls)
        .execute()
    )
    result: dict[str, dict[str, Any]] = {}
    for row in rows.data or []:
        price = row.get("asking_price")
        result[row["listing_url"]] = {
            "id": row["id"],
            "asking_price": float(price) if price is not None else None,
            "has_images": bool(row.get("image_urls")),
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
        # Comuni a entrambe le categorie (NLP + venditore + pHash).
        "image_hash": meta.get("image_hash"),
        "features": meta.get("features"),
        "seller_id": meta.get("seller_id"),
        "seller_type": meta.get("seller_type"),
    }
    if category == "automobile":
        payload.update(
            {
                "year": meta.get("year"),
                "km": meta.get("km"),
                "transmission": meta.get("transmission"),
                "fuel": meta.get("fuel"),
                "defects_noted": meta.get("defects_noted"),
                "urgency_flags": meta.get("urgency_flags"),
            }
        )
    return payload


# Colonne introdotte dalle migrazioni 09/10: se lo schema live non le ha ancora,
# l'insert le rimuove e riprova (lo sniper non si blocca in attesa della migrazione).
_MISSING_COL_RE = re.compile(r"'([\w]+)' column")


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

    # Fino a N tentativi: a ogni PGRST204 su colonna assente la rimuoviamo e
    # riproviamo (copre gli schemi non ancora migrati a 09/10).
    for _ in range(8):
        try:
            inserted = client.table(table).insert(payloads).execute()
            return inserted.data or []
        except Exception as exc:
            column = _missing_column(exc)
            if column is None:
                raise
            logger.warning(
                "Colonna '%s' assente in %s: la ignoro nell'insert "
                "(applica le migrazioni 09/10 per abilitarla).",
                column,
                table,
            )
            for payload in payloads:
                payload.pop(column, None)
    # Ultimo tentativo, lasciando propagare un eventuale errore residuo.
    return client.table(table).insert(payloads).execute().data or []


def _missing_column(exc: Exception) -> str | None:
    """Estrae il nome della colonna mancante da un errore PostgREST PGRST204."""
    if "PGRST204" not in str(exc) and "schema cache" not in str(exc):
        return None
    match = _MISSING_COL_RE.search(str(exc))
    return match.group(1) if match else None


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
        # Auto-riparazione immagini: righe già in DB ma senza foto (es. inserite
        # dal Backfill con download_images=False) vengono riempite quando lo
        # Sniper le rivede con la galleria scaricata.
        if not row.get("has_images") and listing.image_urls:
            patch["image_urls"] = listing.image_urls
            image_hash = (listing.metadata or {}).get("image_hash")
            if image_hash:
                patch["image_hash"] = image_hash
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

    stored_history = 0
    if history_rows:
        try:
            client.table("price_history").insert(history_rows).execute()
            stored_history = len(history_rows)
        except Exception:
            # Lo storico è supplementare: se price_history manca/fallisce, i
            # prezzi sono comunque aggiornati — non facciamo crashare il giro.
            logger.warning(
                "price_history non disponibile: %d cali di prezzo non "
                "storicizzati (crea la tabella price_history per lo storico).",
                len(history_rows),
            )

    return {
        "updated": updated,
        "price_drops": price_drops,
        "history_stored": stored_history,
    }


ACTIVE_STATUSES = ("nuovo", "visto")


def find_republished(
    client: Client, table: str, new_listings: list[ScrapedListing]
) -> dict[str, dict[str, Any]]:
    """Mappa image_hash → {id, listing_url} per gli hash già presenti in `table`.

    Un pHash già a DB sotto un altro listing_url = stesso annuncio ripubblicato.
    """
    hashes = list(
        {
            h
            for listing in new_listings
            if (h := (listing.metadata or {}).get("image_hash"))
        }
    )
    if not hashes:
        return {}
    try:
        rows = (
            client.table(table)
            .select("id, listing_url, image_hash")
            .in_("image_hash", hashes)
            .execute()
        )
    except Exception:
        # Colonna image_hash non ancora presente (migrazione 09): niente dedup
        # anti-ripubblicazione, ma lo sniper non si blocca.
        logger.warning(
            "image_hash assente in %s: dedup anti-ripubblicazione disattivata "
            "(applica la migrazione 09).",
            table,
        )
        return {}
    result: dict[str, dict[str, Any]] = {}
    for row in rows.data or []:
        h = row.get("image_hash")
        if h and h not in result:
            result[h] = {"id": row["id"], "listing_url": row["listing_url"]}
    return result


def apply_republish_updates(
    client: Client,
    table: str,
    republished: list[tuple[str, ScrapedListing]],
) -> int:
    """Ripubblicazioni: sposta il record esistente sul nuovo URL (storico intatto,
    nessun duplicato); rinfresca updated_at e la galleria."""
    now = datetime.now(timezone.utc).isoformat()
    for old_id, listing in republished:
        patch: dict[str, Any] = {"listing_url": listing.url, "updated_at": now}
        if listing.image_urls:
            patch["image_urls"] = listing.image_urls
        client.table(table).update(patch).eq("id", old_id).execute()
    return len(republished)


def apply_shadow_dealer(
    client: Client, table: str, listings: list[ScrapedListing]
) -> int:
    """Smaschera i finti privati: un venditore marcato 'privato' con > 3 annunci
    attivi in `table` viene riclassificato 'finto_privato' (in place sui metadata)."""
    privati = [
        listing
        for listing in listings
        if (listing.metadata or {}).get("seller_type") == "privato"
        and (listing.metadata or {}).get("seller_id")
    ]
    if not privati:
        return 0

    batch_counts = Counter(listing.metadata["seller_id"] for listing in privati)
    flagged: set[str] = set()
    for seller_id, batch_n in batch_counts.items():
        try:
            db_n = (
                client.table(table)
                .select("id", count="exact")
                .eq("seller_id", seller_id)
                .in_("status", list(ACTIVE_STATUSES))
                .limit(1)
                .execute()
                .count
                or 0
            )
        except Exception:
            # Colonna seller_id non ancora presente (migrazione 10): Shadow
            # Dealer disattivato, sniper comunque operativo.
            logger.warning(
                "seller_id assente in %s: Shadow Dealer disattivato "
                "(applica la migrazione 10).",
                table,
            )
            return 0
        if db_n + batch_n > 3:
            flagged.add(seller_id)

    reclassified = 0
    for listing in privati:
        if listing.metadata["seller_id"] in flagged:
            listing.metadata["seller_type"] = "finto_privato"
            reclassified += 1
    return reclassified


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
        return {"new": 0, "updated": 0, "price_drops": 0, "republished": 0}

    table = opportunities_table(category)
    db = get_supabase_client()
    existing = await asyncio.to_thread(
        get_existing_opportunities, db, table, [listing.url for listing in listings]
    )

    new_listings = [listing for listing in listings if listing.url not in existing]
    dup_listings = [listing for listing in listings if listing.url in existing]

    # Immagini + pHash per i nuovi (necessari alla dedup anti-ripubblicazione).
    if download_images and new_listings:
        new_listings = await scraper.store_images(new_listings)

    # Auto-riparazione: duplicati la cui riga in DB è senza immagini → scarica
    # ora la galleria così apply_price_updates può riempire image_urls.
    if download_images and dup_listings:
        needs_img = [
            listing
            for listing in dup_listings
            if not existing[listing.url].get("has_images")
        ]
        if needs_img:
            healed = {
                listing.url: listing
                for listing in await scraper.store_images(needs_img)
            }
            dup_listings = [healed.get(l.url, l) for l in dup_listings]

    # Anti-ripubblicazione (pHash): se il nuovo URL ha una foto già a DB, è lo
    # stesso annuncio ripubblicato → aggiorna il vecchio record, non duplicare.
    republished_map = await asyncio.to_thread(find_republished, db, table, new_listings)
    republished: list[tuple[str, ScrapedListing]] = []
    truly_new: list[ScrapedListing] = []
    claimed_ids: set[str] = set()
    for listing in new_listings:
        image_hash = (listing.metadata or {}).get("image_hash")
        match = republished_map.get(image_hash) if image_hash else None
        if match and match["id"] not in claimed_ids:
            claimed_ids.add(match["id"])
            republished.append((match["id"], listing))
        else:
            truly_new.append(listing)

    # Shadow Dealer (solo auto): riclassifica i finti privati prima dell'insert.
    if category == "automobile" and truly_new:
        await asyncio.to_thread(apply_shadow_dealer, db, table, truly_new)

    inserted = await asyncio.to_thread(
        insert_opportunities, db, table, category, target_id, truly_new
    )
    republished_count = await asyncio.to_thread(
        apply_republish_updates, db, table, republished
    )
    updates = await asyncio.to_thread(
        apply_price_updates, db, table, existing, dup_listings
    )

    return {
        "new": len(inserted),
        "updated": updates["updated"],
        "price_drops": updates["price_drops"],
        "republished": republished_count,
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
        "republished": result.get("republished", 0),
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
    """Upsert today's market snapshot.

    Isolamento pieno per target quando ``market_trends`` ha la colonna
    ``target_id`` (uno snapshot per target/giorno). Se lo schema live non ce
    l'ancora — non fa crashare il Motore Notturno: ripiega su un upsert manuale
    idempotente per (product_id, giorno), così le medie di mercato vengono
    comunque generate e la dashboard mostra i margini.
    """
    db = client or get_supabase_client()
    today = date.today().isoformat()
    base = {"product_id": product_id, "trend_date": today, **stats}

    if target_id is not None:
        try:
            result = (
                db.table("market_trends")
                .upsert(
                    {**base, "target_id": target_id},
                    on_conflict="target_id,trend_date",
                )
                .execute()
            )
            return result.data[0] if result.data else None
        except Exception:
            logger.debug(
                "market_trends senza target_id: fallback su (product_id, giorno) "
                "per '%s' (applica la migrazione 08 per l'isolamento per target).",
                product_id,
            )

    # Fallback: schema senza target_id → upsert manuale su (product_id, giorno).
    existing = (
        db.table("market_trends")
        .select("id")
        .eq("product_id", product_id)
        .eq("trend_date", today)
        .limit(1)
        .execute()
    )
    if existing.data:
        result = (
            db.table("market_trends")
            .update(base)
            .eq("id", existing.data[0]["id"])
            .execute()
        )
    else:
        result = db.table("market_trends").insert(base).execute()
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

    # Escludiamo dalla media di mercato le auto squalificate dall'NLP
    # (incidentata/fuso): inquinerebbero l'IQR verso il basso.
    prices = [
        float(listing.price_amount)
        for listing in listings
        if listing.price_amount is not None
        and not (listing.metadata or {}).get("exclude_from_iqr")
    ]
    excluded = sum(
        1 for listing in listings if (listing.metadata or {}).get("exclude_from_iqr")
    )
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
        "excluded_wrecks": excluded,
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
