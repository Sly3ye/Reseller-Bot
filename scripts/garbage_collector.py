"""Garbage Collector — decadimento annunci (da eseguire settimanalmente).

Scorre gli annunci ancora attivi (status 'nuovo'/'attivo') in
``live_opportunities_auto`` e ``live_opportunities_tech``, interroga l'URL
reale su Subito e, se l'annuncio non esiste più (404 o redirect a una pagina
diversa dall'annuncio), lo marca ``venduto_rimosso`` registrando la data in
``updated_at``.

Esegui dalla root:
  python scripts/garbage_collector.py [category]
  es. python scripts/garbage_collector.py automobile
"""

import asyncio
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.database import get_supabase_client  # noqa: E402

ACTIVE_STATUSES = ("nuovo", "visto")
REMOVED_STATUS = "venduto_rimosso"
REMOVED_STATUS_FALLBACK = "scaduto"  # valore già nell'enum se manca la migr. 11
PAGE_SIZE = 1000          # righe per query Supabase
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
    """True se l'annuncio non è più disponibile (404 o redirect fuori annuncio)."""
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
            print(
                f"    (enum senza '{REMOVED_STATUS}': uso '{status}' — "
                f"applica la migrazione 11)"
            )
            db.table(table).update(
                {"status": status, "updated_at": now}
            ).in_("id", chunk).execute()
    return status


async def collect_table(db, table: str) -> dict[str, int]:
    rows = await asyncio.to_thread(fetch_active, db, table)
    print(f"  {table}: {len(rows)} annunci attivi da verificare")
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
    print(f"  {table}: {len(removed_ids)} marcati '{REMOVED_STATUS}'")
    return {"checked": len(rows), "removed": len(removed_ids)}


async def main() -> None:
    category = sys.argv[1] if len(sys.argv) > 1 else None
    if category and category not in TABLES:
        print(f"Categoria sconosciuta '{category}'. Usa: {', '.join(TABLES)}")
        return

    tables = [TABLES[category]] if category else list(TABLES.values())
    db = get_supabase_client()

    print(f"Garbage Collector: verifico {', '.join(tables)}")
    grand = {"checked": 0, "removed": 0}
    for table in tables:
        result = await collect_table(db, table)
        grand["checked"] += result["checked"]
        grand["removed"] += result["removed"]

    print(
        f"\n=== GC COMPLETATO === verificati {grand['checked']}, "
        f"rimossi (venduto_rimosso) {grand['removed']}"
    )


if __name__ == "__main__":
    asyncio.run(main())
