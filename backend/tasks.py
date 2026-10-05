import asyncio
import logging
import re
import statistics
import uuid
from collections import Counter
from dataclasses import asdict
from datetime import date, datetime, timedelta, timezone
from typing import Any

from backend.core.database import Client

from backend.core.database import get_db, has_column
from backend.scrapers import ScrapedListing, SubitoScraper
from backend.scrapers.subito import ScraperBlockedError, current_job, pacer
from backend.services.health import record_run
from backend.services.republish import find_revivable
from backend.core.config import settings
from backend.services.notifications import notify_deals, notify_system_alert
from backend.services.variants import resolve_variant

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
    db = client or get_db()

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
        raise RuntimeError("Il DB non ha restituito il prodotto creato.")

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
    """Map listing_url → {id, asking_price, ...} per le righe già in `table`."""
    if not urls:
        return {}
    with_published = has_column(table, "published_at", client)
    can_raw = has_column(table, "raw_image_urls", client)
    can_car = table.endswith("_auto") and has_column(table, "car_model", client)
    can_geo = has_column(table, "geo_lat", client)
    cols = ("id, listing_url, asking_price, image_urls" + (", car_model" if can_car else "")
            + (", geo_lat" if can_geo else ""))
    rows = (
        client.table(table)
        .select(cols + (", published_at" if with_published else ""))
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
            # False se la colonna manca: allora non si tenta il riempimento.
            "missing_published": with_published and not row.get("published_at"),
            # Prima data vista: confronto per i riposizionamenti (record_bumps).
            "published_at": row.get("published_at"),
            "can_raw": can_raw,
            # Auto salvata prima della migrazione 23: i dati strutturati si
            # riempiono la prima volta che l'annuncio viene rivisto.
            "missing_car": can_car and not row.get("car_model"),
            "missing_geo": can_geo and row.get("geo_lat") is None,
        }
    return result


def _opportunity_payload(
    category: str,
    target_id: str | None,
    listing: ScrapedListing,
    now: str,
    query: str | None = None,
    strict_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # id e found_at/updated_at non hanno DEFAULT nel DDL → li forniamo noi.
    meta = listing.metadata or {}
    # Variante canonica (scrematura BI): bucket pulito per (modello,memoria) tech
    # / (modello,generazione) auto + fascia di condizione.
    variant = resolve_variant(
        category, listing.title, meta, query=query, strict_filters=strict_filters,
        description=listing.description,
    )
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
        "published_at": meta.get("published_at"),
        # Comuni a entrambe le categorie (NLP + venditore + pHash + variante).
        "image_hash": meta.get("image_hash"),
        # URL originali della galleria (migrazione 21): se le foto non si
        # scaricano subito, le recupera dopo services/photo_backfill.py.
        "raw_image_urls": meta.get("raw_images") or None,
        "features": meta.get("features"),
        "seller_id": meta.get("seller_id"),
        "seller_type": meta.get("seller_type"),
        "color": meta.get("color"),
        "variant_key": variant["variant_key"],
        "condition_tier": variant["condition_tier"],
        **{k: meta.get(k) for k in GEO_FIELDS},
    }
    if category == "automobile":
        payload.update(
            {
                "year": meta.get("year"),
                "km": meta.get("km"),
                "transmission": meta.get("transmission"),
                "fuel": meta.get("fuel"),
                **{k: meta.get(k) for k in CAR_FIELDS},
                "defects_noted": meta.get("defects_noted"),
                "urgency_flags": meta.get("urgency_flags"),
            }
        )
    else:
        # Variante tech (migrazioni 12/15): segmentazione + segnale NLP.
        payload.update(
            {
                "storage_gb": meta.get("storage_gb"),
                "battery_pct": meta.get("battery_pct"),
                "defects_noted": meta.get("defects_noted"),
                "urgency_flags": meta.get("urgency_flags"),
            }
        )
    return payload


# Colonne introdotte dalle migrazioni 09/10: se lo schema live non le ha ancora,
# l'insert le rimuove e riprova (lo sniper non si blocca in attesa della migrazione).
_MISSING_COL_RE = re.compile(r"'([\w]+)' column")
# Postgres self-hosted (psycopg): 'column "x" of relation "t" does not exist'.
_MISSING_COL_PG_RE = re.compile(r'column "(\w+)" of relation "\w+" does not exist')


def insert_opportunities(
    client: Client,
    table: str,
    category: str,
    target_id: str | None,
    listings: list[ScrapedListing],
    query: str | None = None,
    strict_filters: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Inserisce opportunità nuove (asking_price è NOT NULL → serve il prezzo)."""
    now = datetime.now(timezone.utc).isoformat()
    payloads = [
        _opportunity_payload(category, target_id, listing, now, query, strict_filters)
        for listing in listings
        if listing.price_amount is not None
    ]
    if not payloads:
        return []

    # Fino a N tentativi: a ogni PGRST204 su colonna assente la rimuoviamo e
    # riproviamo (copre gli schemi non ancora migrati a 09/10).
    for _ in range(8):
        try:
            # on conflict do nothing: se nel frattempo un altro job (inventario
            # vs sweep) ha inserito lo stesso URL, non salta tutto il lotto.
            inserted = client.table(table).upsert(
                payloads, on_conflict="listing_url", ignore_duplicates=True
            ).execute()
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
    return client.table(table).upsert(
        payloads, on_conflict="listing_url", ignore_duplicates=True
    ).execute().data or []


def _missing_column(exc: Exception) -> str | None:
    """Estrae il nome della colonna mancante da un errore PostgREST PGRST204
    o dal suo equivalente psycopg (UndefinedColumn)."""
    pg_match = _MISSING_COL_PG_RE.search(str(exc))
    if pg_match:
        return pg_match.group(1)
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
    """Annunci già presenti: aggiorna updated_at; ogni variazione di prezzo
    (calo o rialzo) va in price_history; sui CALI il vecchio prezzo passa in
    original_price e parte l'evento per gli alert."""
    now = datetime.now(timezone.utc).isoformat()
    updated = 0
    price_drops = 0
    history_rows: list[dict[str, Any]] = []
    drop_events: list[dict[str, Any]] = []
    bumps: list[tuple[Any, datetime]] = []

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
        elif not row.get("has_images") and row.get("can_raw") and (listing.metadata or {}).get("raw_images"):
            # Senza foto e non scaricate in questo giro (inventario): si
            # aggiornano le URL della galleria per il backfill delle foto.
            patch["raw_image_urls"] = listing.metadata["raw_images"]
        # Righe salvate prima della migrazione 19: la data di pubblicazione
        # arriva la prima volta che l'annuncio viene rivisto.
        if row.get("missing_geo") and (listing.metadata or {}).get("geo_lat") is not None:
            patch.update({k: listing.metadata.get(k) for k in GEO_FIELDS})
        if row.get("missing_car") and (listing.metadata or {}).get("car_model"):
            patch.update({k: listing.metadata.get(k) for k in CAR_FIELDS})
        published = (listing.metadata or {}).get("published_at")
        if row.get("missing_published") and published:
            patch["published_at"] = published
        elif published and (shown := is_bump(published, row.get("published_at"))):
            bumps.append((listing_id, shown))
        if new_price is not None and old_price is not None and new_price > old_price:
            # Rialzo: si registra anche quello (prima andava perso, e il prezzo
            # in DB restava quello vecchio più basso). Niente alert né
            # original_price: quelli raccontano i ribassi.
            patch["asking_price"] = new_price
            history_rows.append(
                {
                    "id": str(uuid.uuid4()),
                    "listing_id": listing_id,
                    "old_price": old_price,
                    "new_price": new_price,
                }
            )
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
            # Evento dettagliato per le notifiche Telegram (calo di prezzo).
            drop_events.append(
                {
                    "listing_id": listing_id,
                    "title": listing.title,
                    "listing_url": listing.url,
                    "old_price": float(old_price),
                    "new_price": float(new_price),
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

    try:
        bumped = record_bumps(table, bumps)
    except Exception:
        logger.exception("Riposizionamenti non registrati")
        bumped = 0

    return {
        "updated": updated,
        "price_drops": price_drops,
        "history_stored": stored_history,
        "drop_events": drop_events,
        "bumps": bumped,
    }


# Riposizionamento: quando il venditore rimette in cima l'annuncio, la data
# mostrata da Subito (display_iso8601) torna "adesso"; published_at resta la
# prima vista. Sotto l'ora è rumore (fusi orari, arrotondamenti).
BUMP_MIN_GAP = timedelta(hours=1)


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def is_bump(shown: Any, first_published: Any) -> datetime | None:
    """Data mostrata ora se è un riposizionamento rispetto alla prima, altrimenti None."""
    shown_dt, first_dt = _as_dt(shown), _as_dt(first_published)
    if shown_dt and first_dt and shown_dt - first_dt > BUMP_MIN_GAP:
        return shown_dt
    return None


def record_bumps(table: str, bumps: list[tuple[Any, datetime]]) -> int:
    """Eventi 'riposizionato' in listing_events (migrazione 26), uno per ogni
    nuova data mostrata: inventario e sweep rivedono lo stesso annuncio
    riposizionato più volte e non va contato ogni volta."""
    import json  # noqa: PLC0415

    from backend.core.database import _get_pool  # noqa: PLC0415

    if not bumps or not has_column("listing_events", "kind"):
        return 0
    category = "automobile" if table.endswith("_auto") else "smartphone"
    ids = list({str(listing_id) for listing_id, _ in bumps})
    with _get_pool().connection() as conn:
        last = {
            str(r["listing_id"]): r["shown"]
            for r in conn.execute(
                "select listing_id, max((info->>'shown_at')::timestamptz) as shown "
                "from public.listing_events where kind = 'riposizionato' and listing_id = any(%s::uuid[]) "
                "group by listing_id",
                (ids,),
            ).fetchall()
        }
        rows = []
        for listing_id, shown in bumps:
            prev = last.get(str(listing_id))
            if prev is None or shown - prev > BUMP_MIN_GAP:
                rows.append((str(listing_id), category, shown, json.dumps({"shown_at": shown.isoformat()})))
                last[str(listing_id)] = shown
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "insert into public.listing_events (listing_id, category, kind, at, info) "
                    "values (%s, %s, 'riposizionato', %s, %s::jsonb)",
                    rows,
                )
    return len(rows)


ACTIVE_STATUSES = ("nuovo", "visto")
# Dati strutturati delle auto (migrazione 23), dallo scraper ai record.
CAR_FIELDS = ("car_brand", "car_model", "car_version", "power_kw", "body_type",
              "doors", "register_month", "emission_class")
# Posizione (migrazione 24), entrambe le categorie.
GEO_FIELDS = ("geo_lat", "geo_lon", "province", "region")


def find_republished(
    client: Client, table: str, new_listings: list[ScrapedListing]
) -> dict[str, list[dict[str, Any]]]:
    """Mappa image_hash → righe già in `table` con quella prima foto.

    Il match vero lo decide ``republish_match``: la sola foto uguale non basta
    (foto stock condivise tra negozi diversi).
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
            .select("id, listing_url, image_hash, seller_id, status")
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
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows.data or []:
        if h := row.get("image_hash"):
            result.setdefault(h, []).append(row)
    return result


def republish_match(
    listing: ScrapedListing, rows: list[dict[str, Any]], claimed: set[str]
) -> dict[str, Any] | None:
    """La riga di cui ``listing`` è la ripubblicazione, o None.

    Stessa prima foto E stesso venditore. Se uno dei due venditori è ignoto,
    solo un record già sparito (un annuncio ancora attivo con la stessa foto
    è più probabilmente un altro pezzo con foto di catalogo). Prima la regola
    era la sola foto: due negozi con la stessa foto stock si fondevano."""
    seller = (listing.metadata or {}).get("seller_id")
    for row in rows:
        if row["id"] in claimed or row.get("listing_url") == listing.url:
            continue
        if seller and row.get("seller_id"):
            if str(row["seller_id"]) == str(seller):
                return row
        elif row.get("status") not in ACTIVE_STATUSES:
            return row
    return None


def apply_republish_updates(
    client: Client,
    table: str,
    republished: list[tuple[str, ScrapedListing]],
) -> int:
    """Ripubblicazioni: sposta il record esistente sul nuovo URL (storico intatto,
    nessun duplicato); rinfresca updated_at, prezzo e galleria.

    Se il record era già stato marcato sparito, torna ATTIVO: l'annuncio è di
    nuovo online, e lasciarlo "venduto" contava una vendita mai avvenuta."""
    now = datetime.now(timezone.utc).isoformat()
    for old_id, listing in republished:
        patch: dict[str, Any] = {"listing_url": listing.url, "updated_at": now}
        if listing.image_urls:
            patch["image_urls"] = listing.image_urls
        if listing.price_amount is not None:
            patch["asking_price"] = listing.price_amount
        client.table(table).update(patch).eq("id", old_id).execute()
        client.table(table).update({"status": "nuovo"}).eq("id", old_id).in_(
            "status", ["venduto_rimosso", "scaduto"]
        ).execute()
    return len(republished)


def apply_shadow_dealer(
    client: Client, table: str, listings: list[ScrapedListing]
) -> int:
    """Smaschera i finti privati: un venditore marcato 'privato' con più di N
    annunci attivi in `table` viene riclassificato 'finto_privato' (in place sui
    metadata). N = 3 per gli iPhone; 1 per le auto: la tabella contiene solo i
    modelli tracciati, e un privato con due di quelle auto in vendita è quasi
    sempre un rivenditore."""
    threshold = 1 if table.endswith("_auto") else 3
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
        if db_n + batch_n > threshold:
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
    query: str | None = None,
    strict_filters: dict[str, Any] | None = None,
) -> dict[str, int]:
    """Routing + UPSERT condiviso da Sniper e Backfill.

    Instrada sulla tabella per categoria, deduplica su listing_url, scarica le
    immagini SOLO per i nuovi (se richiesto) e li inserisce; per gli esistenti
    aggiorna updated_at e gestisce i cali di prezzo (price_history).
    """
    if not listings:
        return {
            "new": 0,
            "updated": 0,
            "price_drops": 0,
            "republished": 0,
            "inserted_rows": [],
            "drop_events": [],
        }

    table = opportunities_table(category)
    db = get_db()
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
        match = (
            republish_match(listing, republished_map.get(image_hash, []), claimed_ids)
            if image_hash else None
        )
        if match:
            claimed_ids.add(match["id"])
            republished.append((match["id"], listing))
        else:
            truly_new.append(listing)

    # Anti-ripubblicazione SENZA foto (righe da inventario, o foto cambiate):
    # stesso venditore + stessa variante + prezzo vicino a un record sparito
    # da poco → è lo stesso oggetto rimesso online, non un annuncio nuovo.
    if truly_new:
        candidates = []
        for listing in truly_new:
            meta = listing.metadata or {}
            variant = resolve_variant(
                category, listing.title, meta, query=query, strict_filters=strict_filters,
                description=listing.description,
            )
            candidates.append({
                "listing": listing, "seller_id": meta.get("seller_id"),
                "variant_key": variant["variant_key"], "title": listing.title,
                "description": listing.description,
                "price": listing.price_amount,
            })
        revived = await asyncio.to_thread(find_revivable, db, table, category, candidates)
        revived_urls = set()
        for cand, old in revived:
            if old["id"] in claimed_ids:
                continue
            claimed_ids.add(old["id"])
            republished.append((old["id"], cand["listing"]))
            revived_urls.add(cand["listing"].url)
        truly_new = [l for l in truly_new if l.url not in revived_urls]

    # Shadow Dealer (solo auto): riclassifica i finti privati prima dell'insert.
    if category == "automobile" and truly_new:
        await asyncio.to_thread(apply_shadow_dealer, db, table, truly_new)

    inserted = await asyncio.to_thread(
        insert_opportunities,
        db, table, category, target_id, truly_new, query, strict_filters,
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
        "inserted_rows": inserted,
        "drop_events": updates.get("drop_events", []),
    }


async def scrape_subito_and_save(
    query: str = "iPhone 13 Pro",
    category: str = "smartphone",
    pages: int = 1,
    strict_filters: dict[str, Any] | None = None,
    target_id: str | None = None,
    since: datetime | None = None,
) -> dict[str, Any]:
    """Cecchino Live: processa in blocco 'pages' pagine dell'API con routing/UPSERT.

    Con ``since`` (ultima scansione del target) ``pages`` diventa un tetto: si
    pagina solo finché non ci si ricongiunge con la scansione precedente.

    1) Fetch del blocco (filtri nativi + anti-spam applicati).
    2) Routing su _auto/_tech, dedup su listing_url.
    3) Immagini SOLO per i nuovi (CDN diretta) + insert; esistenti → updated_at
       e price_history sui cali di prezzo.
    """
    current_job.set("cecchino")
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
        since=since,
    )

    result = await persist_opportunities(
        scraper, category, target_id, listings, download_images=True,
        query=query, strict_filters=strict_filters,
    )

    # Gli alert Telegram non partono più qui (per-target, a margine grezzo): li
    # gestisce run_sniper_all_products a fine giro, con l'intelligence completa
    # (valore equo per variante + Deal Score + anti-truffa AI). Espongo le
    # righe nuove e i cali di prezzo perché il chiamante possa arricchirle.
    return {
        "query": query,
        "category": category,
        "pages": scraper.last_search["pages"],
        "gap": scraper.last_search["gap"],
        "target_id": target_id,
        "table": opportunities_table(category),
        "scraped_count": len(listings),
        "new_count": result["new"],
        "updated_count": result["updated"],
        "price_drops": result["price_drops"],
        "republished": result.get("republished", 0),
        "inserted_rows": result.get("inserted_rows", []),
        "drop_events": result.get("drop_events", []),
        "saved_count": result["new"],
    }


def get_target_market_avg(client: Client, target_id: str) -> float | None:
    """Ultima media di mercato (market_trends) per il target, se esiste."""
    try:
        rows = (
            client.table("market_trends")
            .select("avg_price, trend_date")
            .eq("target_id", target_id)
            .order("trend_date", desc=True)
            .limit(1)
            .execute()
        )
    except Exception:
        return None
    if not rows.data:
        return None
    avg = rows.data[0].get("avg_price")
    try:
        return float(avg) if avg is not None else None
    except (TypeError, ValueError):
        return None


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
    db = client or get_db()
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
    current_job.set("notturno")
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


# Categorie coperte per intero dalla ricerca ampia: la media notturna si
# calcola dagli annunci attivi già nel DB, senza nuove richieste a Subito.
# Con la raccolta completa delle auto anche i loro trend si calcolano dal DB
# (niente scraping per target nel Motore Notturno).
DB_TREND_CATEGORIES = frozenset({"smartphone", "automobile"} if settings.auto_full_category
                                else {"smartphone"})


def nightly_trend_from_db(target: dict[str, Any]) -> dict[str, Any]:
    """Media/IQR del target dagli annunci ATTIVI nel DB (solo condizioni sane)."""
    from backend.services.variants import is_healthy  # noqa: PLC0415

    db = get_db()
    table = opportunities_table(target["category"])
    rows: list[dict[str, Any]] = []
    start = 0
    while True:
        page = (
            db.table(table).select("asking_price, condition_tier")
            .eq("target_id", target["id"]).in_("status", list(ACTIVE_STATUSES))
            .range(start, start + 999).execute().data or []
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000
    prices = [
        float(r["asking_price"]) for r in rows
        if r.get("asking_price") is not None and is_healthy(r.get("condition_tier") or "buono")
    ]
    stats = compute_market_stats(prices)
    product, _ = get_or_create_product(target["query"], target["category"])
    trend = save_market_trend(target["id"], str(product["id"]), stats) if stats else None
    return {
        "mode": "nightly_db",
        "query": target["query"],
        "target_id": target["id"],
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
        if target["category"] in DB_TREND_CATEGORIES:
            try:
                outcome = await asyncio.to_thread(nightly_trend_from_db, target)
                results.append(outcome)
                logger.info("Nightly (DB) '%s': %s annunci", query, outcome["prices_considered"])
            except Exception:
                logger.exception("Nightly (DB) failed for target '%s'", query)
                results.append({"query": query, "error": True})
            continue
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
    db = client or get_db()
    query = (
        db.table("target_models")
        .select("id, category, query, strict_filters, last_scanned")
        .eq("is_active", True)
    )
    if category:
        query = query.eq("category", category)
    return query.execute().data or []


def update_target_last_scanned(
    target_id: str,
    client: Client | None = None,
    scanned_at: datetime | None = None,
) -> None:
    db = client or get_db()
    db.table("target_models").update(
        {"last_scanned": (scanned_at or datetime.now(timezone.utc)).isoformat()}
    ).eq("id", target_id).execute()


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


# Prima scansione di un target (mai visto): si recupera al massimo un giorno.
FIRST_SCAN_LOOKBACK = timedelta(hours=24)
# Margine sul ricongiungimento: copre gli annunci pubblicati mentre la
# scansione precedente era in corso e piccole differenze di orologio.
# Margine dietro il segnalibro: il ritardo di indicizzazione misurato il
# 2026-10-05 è ~6 minuti (l'annuncio più recente in pagina 1 ha 6 minuti).
# 2 ore erano troppe: la data mostrata da Subito si RESETTA coi
# riposizionamenti, quindi ogni giro rileggeva ore di annunci vecchi rimessi in
# cima (lo sweep auto 20–30 pagine a giro, ~1.200 richieste al giorno). I rari
# annunci moderati più tardi li recupera l'inventario notturno.
SINCE_MARGIN = timedelta(minutes=20)


async def notify_new_rows(
    new_by_cat: dict[str, list[dict[str, Any]]],
    drops_by_cat: dict[str, list[dict[str, Any]]],
) -> None:
    """Alert sulle righe appena inserite e sui ribassi: usato a fine giro
    (``finish_run``) e dalla testa della coda (``sweep.head_poll``), che
    notifica entro secondi invece che a fine giro."""
    # Alert Telegram "intelligenti": una passata a fine giro per categoria.
    # Si arricchiscono le NUOVE righe con la stessa BI della dashboard e si
    # notifica SOLO ciò che è un vero affare (classe "affare" + Deal Score ≥
    # soglia), scartando sospetti/truffe. I cali di prezzo vanno comunque.
    if new_by_cat or drops_by_cat:
        from backend.services.reads import enrich_for_alerts  # lazy: evita import circolare
        from backend.services import settings_store

        min_score = settings_store.get_all()["alert_min_score"]
        db = get_db()
        for cat in set(new_by_cat) | set(drops_by_cat):
            new_rows = new_by_cat.get(cat, [])
            drops = drops_by_cat.get(cat, [])
            try:
                items = await asyncio.to_thread(enrich_for_alerts, cat, new_rows, db)
                if cat == "automobile":
                    # Auto: margine netto dopo i costi e criteri del compratore
                    # (services/car_alerts.py), non classe affare + score.
                    from backend.services.car_alerts import select_car_alerts  # noqa: PLC0415

                    cars = select_car_alerts(items, settings_store.get_all())
                    await notify_deals(db, cat, cars, drops, [])
                    continue
                # Mai un alert su una valutazione con meno di 6 campioni
                # (mediana di 3 prezzi chiesti = rumore, non un affare).
                items = [it for it in items if it.get("valuationConfidence") != "bassa"]
                deals = [
                    it
                    for it in items
                    if it.get("dealClass") == "affare"
                    and (it.get("score") or 0) >= min_score
                ]
                # Il business principale: rotti che, riparati, rendono sopra
                # soglia (margine netto già al netto di ricambio, sconto per
                # parti non originali e magazzino), rischio non alto.
                min_repair = settings_store.get_all()["alert_min_repair_margin_eur"]
                deal_ids = {it.get("id") for it in deals}
                repairs = [
                    it
                    for it in items
                    if it.get("id") not in deal_ids
                    and ((it.get("repair") or {}).get("netMarginEur") or 0) >= min_repair
                    and (it.get("risk") or {}).get("level") != "alto"
                ]
                await notify_deals(db, cat, deals, drops, repairs)
            except Exception:
                # Le notifiche sono supplementari: mai far fallire il giro.
                logger.exception("Alert intelligenti falliti (%s)", cat)



async def finish_run(
    label: str,
    n_targets: int,
    n_ok: int,
    n_failed: int,
    total_scraped: int,
    total_new: int,
    total_requests: int,
    gaps: list[str],
    blocked: bool,
    new_by_cat: dict[str, list[dict[str, Any]]],
    drops_by_cat: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    """Chiusura comune di un giro di raccolta (Sniper per target o ricerca
    ampia): alert Telegram sulle novità, registrazione in scrape_runs e alert
    di sistema sulle transizioni down/ripristino. Ritorna l'esito di salute."""
    await notify_new_rows(new_by_cat, drops_by_cat)

    # Salute dello scraper: registra il giro e allerta sulle transizioni
    # down/ripristino (Akamai/Subito) — così non si blocca in silenzio.
    if gaps:
        logger.warning(
            "Sniper (%s): %d ricerche non ricongiunte (annunci persi): %s",
            label, len(gaps), ", ".join(gaps),
        )
    health = await asyncio.to_thread(
        record_run,
        label, n_targets, n_ok, n_failed, total_scraped, total_new,
        total_requests, len(gaps),
    )
    if health["went_down"]:
        logger.error("Scraper DOWN (%s): %d/%d target falliti, %d annunci",
                     label, n_failed, n_targets, total_scraped)
        if blocked:
            pace = pacer.snapshot()
            cause = (
                f"Bloccati da Subito (rate limit): pausa automatica di "
                f"{pace['blockedForS'] // 60} min, poi ritmo 1 richiesta/{pace['gapS']:.0f}s."
            )
        else:
            cause = "Nessun blocco 403/429: errore di rete o Subito cambiato — controlla."
        try:
            await notify_system_alert(
                f"🔴 <b>Scraper DOWN</b> ({label})\n"
                f"{n_failed}/{n_targets} target falliti, {total_scraped} annunci raccolti.\n"
                f"{cause}"
            )
        except Exception:
            logger.exception("Alert di sistema (down) fallito")
    elif health["recovered"]:
        try:
            await notify_system_alert(
                f"🟢 <b>Scraper ripristinato</b> ({label}) — "
                f"{total_scraped} annunci nell'ultimo giro."
            )
        except Exception:
            logger.exception("Alert di sistema (recovery) fallito")

    return health


async def run_sniper_all_products(
    category: str | None = None,
    pages: int = 5,
) -> dict[str, Any]:
    """Cecchino Live (scheduled): hunt fresh opportunities for every active target.

    Reads the scraping fleet from ``target_models`` (DB-driven, non hardcoded)
    and, per target, pages back from the newest ad until it meets the previous
    scan (``last_scanned``), up to ``pages`` API blocks. A target that hits the
    cap without catching up has a *gap*: ads were missed and the cadence for
    that category is too slow. ``category`` scopes to one vertical.
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
    n_ok = n_failed = total_scraped = total_new = 0
    # Righe nuove e cali di prezzo accumulati per categoria: gli alert partono
    # UNA volta a fine giro, arricchiti con la BI completa (non per-target).
    new_by_cat: dict[str, list[dict[str, Any]]] = {}
    drops_by_cat: dict[str, list[dict[str, Any]]] = {}
    blocked = False
    total_requests = 0
    gaps: list[str] = []
    # Il ritmo tra una richiesta e l'altra lo impone il pacer globale dello
    # scraper (condiviso con gli altri job): qui niente pause proprie.
    for index, target in enumerate(targets):
        query = target["query"]
        target_category = target["category"]
        strict_filters = target.get("strict_filters") or None
        scan_started = datetime.now(timezone.utc)
        last = _parse_ts(target.get("last_scanned"))
        since = (last - SINCE_MARGIN) if last else scan_started - FIRST_SCAN_LOOKBACK
        try:
            outcome = await scrape_subito_and_save(
                query=query,
                category=target_category,
                pages=pages,
                strict_filters=strict_filters,
                target_id=target["id"],
                since=since,
            )
            # Si timbra l'INIZIO della scansione: un annuncio pubblicato mentre
            # questa era in corso deve risultare "dopo" alla prossima.
            await asyncio.to_thread(
                update_target_last_scanned, target["id"], None, scan_started
            )
            n_ok += 1
            total_scraped += outcome["scraped_count"]
            total_new += outcome["new_count"]
            total_requests += outcome["pages"]
            if outcome["gap"]:
                gaps.append(query)
            if outcome.get("inserted_rows"):
                new_by_cat.setdefault(target_category, []).extend(outcome["inserted_rows"])
            if outcome.get("drop_events"):
                drops_by_cat.setdefault(target_category, []).extend(outcome["drop_events"])
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
        except ScraperBlockedError as exc:
            # Bloccati (o ancora in cooldown): insistere coi target restanti
            # dallo stesso IP allungherebbe il blocco. Si chiude il giro qui.
            blocked = True
            remaining = len(targets) - index
            n_failed += remaining
            logger.warning(
                "Sniper (%s) fermato su '%s': %s — %d target saltati",
                category or "all", query, exc, remaining,
            )
            results.append({"query": query, "error": True, "blocked": True})
            break
        except Exception:
            n_failed += 1
            logger.exception("Sniper failed for '%s'", query)
            results.append({"query": query, "error": True})

    health = await finish_run(
        category or "all", len(targets), n_ok, n_failed, total_scraped, total_new,
        total_requests, gaps, blocked, new_by_cat, drops_by_cat,
    )

    return {
        "mode": "sniper_targets",
        "category": category,
        "targets": len(targets),
        "status": health["status"],
        "results": results,
    }


if __name__ == "__main__":
    print(asyncio.run(scrape_subito_and_save()))
