"""Garbage Collector — decadimento annunci (servizio schedulabile).

Scorre gli annunci ancora attivi (status 'nuovo'/'visto') nelle tabelle
``live_opportunities_auto`` e ``live_opportunities_tech``, interroga l'URL
reale su Subito e, se l'annuncio non esiste più (404/410 o redirect a una
pagina diversa dall'annuncio), lo marca ``venduto_rimosso`` registrando la
data in ``updated_at``.

Oltre alla pulizia del feed, questo è il sensore del TIME-TO-SALE: la
differenza tra ``found_at`` e l'``updated_at`` della rimozione misura in
quanti giorni un annuncio sparisce dal mercato → velocità di rotazione per
modello (vedi backend/services/reads.py). Per questo il GC gira ogni notte
nello scheduler, non più solo a mano.

Le richieste di verifica vanno in connessione diretta, a basso parallelismo,
e si fermano se Subito inizia a bloccare (stesso IP dello Sniper).
"""

from __future__ import annotations

import asyncio
import logging
import random
import re
from datetime import datetime, timezone

from curl_cffi.requests import AsyncSession
from curl_cffi.requests.exceptions import CurlError

from backend.core.config import settings
from backend.core.database import get_db

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("nuovo", "visto")
REMOVED_STATUS = "venduto_rimosso"
REMOVED_STATUS_FALLBACK = "scaduto"  # valore già nell'enum se manca la migr. 11
PAGE_SIZE = 1000          # righe per query
# Da un solo IP (niente proxy) una raffica di migliaia di pagine può far
# scattare il blocco Akamai anche per lo Sniper: poche richieste parallele,
# con una pausa irregolare dopo ognuna.
CHECK_CONCURRENCY = 2
CHECK_PAUSE_S = (0.5, 1.5)
BLOCK_STATUS = (403, 429)
MAX_CONSECUTIVE_BLOCKS = 5  # oltre: il GC si ferma e riprova la notte dopo
UPDATE_CHUNK = 200        # id per UPDATE batch

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) "
    "Gecko/20100101 Firefox/126.0"
)
_LISTING_ID_RE = re.compile(r"-(\d+)\.htm(?:$|[?#])")

TABLES = {
    "automobile": "live_opportunities_auto",
    "smartphone": "live_opportunities_tech",
}


def _listing_id(url: str) -> str | None:
    match = _LISTING_ID_RE.search(url or "")
    return match.group(1) if match else None


def fetch_active(db, table: str) -> list[dict]:
    """Tutte le righe ancora attive di `table` (paginando oltre le 1000)."""
    rows: list[dict] = []
    start = 0
    while True:
        page = (
            db.table(table)
            .select("id, listing_url")
            .in_("status", list(ACTIVE_STATUSES))
            .range(start, start + PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
    return rows


async def is_removed(client: AsyncSession, url: str) -> bool | None:
    """True se l'annuncio non è più disponibile (404/410 o redirect fuori),
    False se è ancora online o il dubbio resta, None se Subito ci sta bloccando."""
    try:
        response = await client.get(url, allow_redirects=True)
    except CurlError:
        return False  # errore di rete transitorio: non marchiamo, riproveremo

    if response.status_code in BLOCK_STATUS:
        return None
    # Subito risponde 410 Gone (talvolta 404) quando l'annuncio non esiste più.
    if response.status_code in (404, 410):
        return True
    if response.status_code >= 400:
        return False  # altri 4xx/5xx: dubbio → conservativi, non marchiamo

    # 2xx dopo eventuali redirect: rimosso se non siamo più sulla pagina annuncio
    # (Subito redirige gli annunci scaduti verso la ricerca/home).
    original_id = _listing_id(url)
    final_id = _listing_id(str(response.url))
    return original_id is not None and final_id != original_id


def mark_removed(db, table: str, ids: list[str]) -> str:
    """Marca gli id come rimossi; ripiega su 'scaduto' se l'enum non ha ancora
    'venduto_rimosso' (migrazione 11 non applicata). Ritorna lo stato usato."""
    now = datetime.now(timezone.utc).isoformat()
    status = REMOVED_STATUS
    for i in range(0, len(ids), UPDATE_CHUNK):
        chunk = ids[i : i + UPDATE_CHUNK]
        try:
            db.table(table).update(
                {"status": status, "updated_at": now}
            ).in_("id", chunk).execute()
        except Exception as exc:
            if "opportunity_status" not in str(exc):
                raise
            status = REMOVED_STATUS_FALLBACK
            logger.warning(
                "Enum senza '%s': uso '%s' (applica la migrazione 11).",
                REMOVED_STATUS,
                status,
            )
            db.table(table).update(
                {"status": status, "updated_at": now}
            ).in_("id", chunk).execute()
    return status


async def collect_table(db, table: str) -> dict[str, int]:
    rows = await asyncio.to_thread(fetch_active, db, table)
    logger.info("GC %s: %d annunci attivi da verificare", table, len(rows))
    return await verify_and_mark(db, table, rows)


async def verify_and_mark(db, table: str, rows: list[dict]) -> dict[str, int]:
    """Verifica le pagine di `rows` ({id, listing_url}) e marca le rimosse."""
    if not rows:
        return {"checked": 0, "removed": 0}

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    removed_ids: list[str] = []
    state = {"checked": 0, "consecutive_blocks": 0, "aborted": False}

    # curl_cffi con impronta browser: le pagine annuncio di Subito sono dietro
    # Akamai (httpx → 403). Connessione diretta.
    async with AsyncSession(
        impersonate=random.choice(settings.impersonate_pool or ["safari"]),
        timeout=20,
    ) as client:

        async def check(row: dict) -> None:
            async with semaphore:
                if state["aborted"]:
                    return
                outcome = await is_removed(client, row["listing_url"])
                await asyncio.sleep(random.uniform(*CHECK_PAUSE_S))
            if outcome is None:
                state["consecutive_blocks"] += 1
                if state["consecutive_blocks"] >= MAX_CONSECUTIVE_BLOCKS:
                    state["aborted"] = True
                return
            state["consecutive_blocks"] = 0
            state["checked"] += 1
            if outcome:
                removed_ids.append(row["id"])

        await asyncio.gather(*(check(row) for row in rows))

    if state["aborted"]:
        logger.warning(
            "GC %s fermato: %d blocchi 403/429 di fila dopo %d verifiche (riprende domani)",
            table, MAX_CONSECUTIVE_BLOCKS, state["checked"],
        )
    if removed_ids:
        await asyncio.to_thread(mark_removed, db, table, removed_ids)
    logger.info("GC %s: %d marcati '%s'", table, len(removed_ids), REMOVED_STATUS)
    return {"checked": state["checked"], "removed": len(removed_ids)}


async def run_garbage_collector(category: str | None = None) -> dict[str, int]:
    """Esegue il GC su una categoria (o tutte). Schedulato ogni notte per le
    auto; il tech usa l'inventario (services/sweep.reconcile_inventory)."""
    tables = [TABLES[category]] if category in TABLES else list(TABLES.values())
    db = get_db()

    grand = {"checked": 0, "removed": 0}
    for table in tables:
        try:
            result = await collect_table(db, table)
        except Exception:
            logger.exception("GC fallito su %s", table)
            continue
        grand["checked"] += result["checked"]
        grand["removed"] += result["removed"]

    logger.info(
        "GC completato: verificati %d, rimossi %d",
        grand["checked"],
        grand["removed"],
    )
    return grand
