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

Le richieste di verifica vanno in connessione DIRETTA (pagine pubbliche,
niente proxy a consumo).
"""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone

import httpx

from backend.core.database import get_db

logger = logging.getLogger(__name__)

ACTIVE_STATUSES = ("nuovo", "visto")
REMOVED_STATUS = "venduto_rimosso"
REMOVED_STATUS_FALLBACK = "scaduto"  # valore già nell'enum se manca la migr. 11
PAGE_SIZE = 1000          # righe per query
CHECK_CONCURRENCY = 10    # richieste HTTP parallele
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


async def is_removed(client: httpx.AsyncClient, url: str) -> bool:
    """True se l'annuncio non è più disponibile (404/410 o redirect fuori)."""
    try:
        response = await client.get(url)
    except httpx.HTTPError:
        return False  # errore di rete transitorio: non marchiamo, riproveremo

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
    if not rows:
        return {"checked": 0, "removed": 0}

    semaphore = asyncio.Semaphore(CHECK_CONCURRENCY)
    removed_ids: list[str] = []

    async with httpx.AsyncClient(
        timeout=20,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
        trust_env=False,
    ) as client:

        async def check(row: dict) -> None:
            async with semaphore:
                if await is_removed(client, row["listing_url"]):
                    removed_ids.append(row["id"])

        await asyncio.gather(*(check(row) for row in rows))

    if removed_ids:
        await asyncio.to_thread(mark_removed, db, table, removed_ids)
    logger.info("GC %s: %d marcati '%s'", table, len(removed_ids), REMOVED_STATUS)
    return {"checked": len(rows), "removed": len(removed_ids)}


async def run_garbage_collector(category: str | None = None) -> dict[str, int]:
    """Esegue il GC su una categoria (o tutte). Schedulato ogni notte."""
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
