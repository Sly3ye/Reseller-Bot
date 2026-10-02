"""Backfill delle foto: scarica le gallerie delle righe salvate senza foto.

L'inventario notturno e il deep sweep salvano gli annunci senza scaricare le
foto (sarebbero ore di download dentro un giro che deve chiudersi), ma ne
tengono le URL originali (``raw_image_urls``, migrazione 21). Qui un job a
intervalli le scarica a lotti dalla CDN delle immagini: host diverso da
hades, quindi nessun costo sul budget di richieste anti-blocco.

Prima gli annunci ATTIVI e più recenti: quando un annuncio sparisce, Subito
toglie anche le foto dalla CDN, quindi conviene prenderle finché ci sono.
Una galleria che risponde 404/410 (annuncio rimosso) viene marcata con
``raw_image_urls = '[]'`` per non riprovarla all'infinito. Un 403/429 è un
blocco della CDN: il lotto si ferma, la coda resta intatta e si riprova dopo
``BLOCK_PAUSE_S``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "live_opportunities_tech"
BATCH = 120           # annunci per giro (~600 foto, ~30 s ogni 2 min)
BLOCK_PAUSE_S = 3600  # dopo un blocco della CDN
# Righe con esito incerto in questo processo: saltate fino al riavvio, così
# una galleria che fallisce sempre non intasa la testa della coda.
_state: dict[str, Any] = {"paused_until": 0.0, "skip": set()}


def _queue(limit: int) -> list[dict[str, Any]]:
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        return conn.execute(
            f"""
            select id, listing_url, raw_image_urls from public.{TABLE}
            where image_urls = '[]'::jsonb and raw_image_urls is not null
              and raw_image_urls <> '[]'::jsonb
              and not (id::text = any(%s))
            order by (status in ('nuovo', 'visto')) desc, found_at desc
            limit %s
            """,
            (list(_state["skip"]), limit),
        ).fetchall()


def _save(results: list[tuple[str, list[str] | None, str | None]]) -> None:
    from psycopg.types.json import Jsonb  # noqa: PLC0415

    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn, conn.cursor() as cur:
        for row_id, stored, image_hash in results:
            if stored is None:
                continue  # esito incerto (rete, blocco): resta in coda
            if stored:
                cur.execute(
                    f"update public.{TABLE} set image_urls = %s, "
                    f"image_hash = coalesce(image_hash, %s) where id = %s",
                    (Jsonb(stored), image_hash, row_id),
                )
            else:
                # Galleria non più disponibile: fuori dalla coda.
                cur.execute(
                    f"update public.{TABLE} set raw_image_urls = '[]'::jsonb where id = %s",
                    (row_id,),
                )


def queue_size() -> int:
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column(TABLE, "raw_image_urls"):
        return 0
    with _get_pool().connection() as conn:
        return conn.execute(
            f"select count(*) as n from public.{TABLE} where image_urls = '[]'::jsonb "
            f"and raw_image_urls is not null and raw_image_urls <> '[]'::jsonb"
        ).fetchone()["n"]


async def fill_missing_photos(limit: int = BATCH) -> dict[str, int]:
    """Un lotto del backfill. Ritorna quanti annunci hanno ora le foto."""
    from backend.core.database import has_column  # noqa: PLC0415
    from backend.scrapers.subito import SubitoScraper  # noqa: PLC0415

    if not has_column(TABLE, "raw_image_urls"):
        return {"done": 0, "gone": 0}
    if time.monotonic() < _state["paused_until"]:
        return {"done": 0, "gone": 0, "paused": True}
    rows = await asyncio.to_thread(_queue, limit)
    if not rows:
        return {"done": 0, "gone": 0}

    scraper = SubitoScraper()
    semaphore = asyncio.Semaphore(scraper.IMAGE_CONCURRENCY)
    async with scraper._make_cdn_client() as client:

        blocked = {"hit": False}

        async def one(row: dict[str, Any]) -> tuple[str, list[str] | None, str | None]:
            urls = list(row["raw_image_urls"] or [])
            async with semaphore:
                if blocked["hit"]:
                    return str(row["id"]), None, None
                stored, image_hash = await scraper._download_and_store(
                    client, urls, row["listing_url"]
                )
                if stored:
                    return str(row["id"]), stored, image_hash
                # Niente scaricato: annuncio rimosso (404/410) o blocco/rete?
                try:
                    status = (await client.get(urls[0])).status_code
                except Exception:
                    return str(row["id"]), None, None
            if status in (403, 429):
                blocked["hit"] = True
                return str(row["id"]), None, None
            return str(row["id"]), ([] if status in (404, 410) else None), None

        results = await asyncio.gather(*(one(r) for r in rows))
    await asyncio.to_thread(_save, results)
    if not blocked["hit"]:
        _state["skip"].update(row_id for row_id, stored, _ in results if stored is None)
    done = sum(1 for _, stored, _ in results if stored)
    gone = sum(1 for _, stored, _ in results if stored == [])
    if blocked["hit"]:
        _state["paused_until"] = time.monotonic() + BLOCK_PAUSE_S
        logger.warning("Foto: la CDN risponde 403/429, pausa di %d min", BLOCK_PAUSE_S // 60)
    logger.info("Foto: %d/%d annunci scaricati, %d gallerie non più disponibili",
                done, len(results), gone)
    return {"done": done, "gone": gone, "blocked": blocked["hit"]}
