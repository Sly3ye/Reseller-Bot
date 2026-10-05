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


# ------------------------------------------------------------------ auto

AUTO_TABLE = "live_opportunities_auto"
# 537k auto × 12 foto a piena risoluzione ≈ 3 TB: impossibile. Per ogni auto
# si salva la PRIMA foto in formato galleria (~50 KB, ~28 GB in tutto) — resta
# anche quando l'annuncio sparisce e dà il pHash anti-ripubblicazione — e le
# altre restano link a Subito (visibili finché l'annuncio è online). La
# galleria completa si scarica solo per le auto che contano (salvate, in
# pipeline, affari segnalati).
AUTO_BATCH = 600
AUTO_GALLERY_BATCH = 20
CAR_IMAGE_RULE = "?rule=gallery-desktop-1x-auto"
_auto_state: dict[str, Any] = {"paused_until": 0.0, "skip": set()}


def _car_rule(url: str) -> str:
    return url.split("?", 1)[0] + CAR_IMAGE_RULE


async def _download_rows(rows: list[dict[str, Any]], state: dict[str, Any], first_only: bool,
                         ) -> list[tuple[str, list[str] | None, str | None]]:
    """Scarica per ogni riga la prima foto (first_only) o le foto mancanti della
    galleria. Ritorna (id, nuova image_urls | [] persa | None incerta, pHash)."""
    from backend.scrapers.subito import SubitoScraper  # noqa: PLC0415

    scraper = SubitoScraper()
    semaphore = asyncio.Semaphore(scraper.IMAGE_CONCURRENCY)
    blocked = {"hit": False}
    async with scraper._make_cdn_client() as client:

        async def one(row: dict[str, Any]) -> tuple[str, list[str] | None, str | None]:
            raw = list(row["raw_image_urls"] or [])
            # Già salvate da noi = non puntano più alla CDN di Subito.
            have = [u for u in (row.get("image_urls") or []) if "sbito.it" not in str(u)]
            todo = raw[:1] if first_only else raw[len(have):]
            async with semaphore:
                if blocked["hit"] or not todo:
                    return str(row["id"]), None, None
                stored, image_hash = await scraper._download_and_store(
                    client, [_car_rule(u) for u in todo], row["listing_url"], start_index=len(have)
                )
                if stored:
                    local = have + stored
                    return str(row["id"]), local + raw[len(local):], image_hash
                try:
                    status = (await client.get(_car_rule(todo[0]))).status_code
                except Exception:
                    return str(row["id"]), None, None
            if status in (403, 429):
                blocked["hit"] = True
                return str(row["id"]), None, None
            return str(row["id"]), ([] if status in (404, 410) else None), None

        results = await asyncio.gather(*(one(r) for r in rows))
    if blocked["hit"]:
        state["paused_until"] = time.monotonic() + BLOCK_PAUSE_S
        logger.warning("Foto auto: la CDN risponde 403/429, pausa di %d min", BLOCK_PAUSE_S // 60)
    else:
        state["skip"].update(row_id for row_id, imgs, _ in results if imgs is None)
    return results


def _save_auto(results: list[tuple[str, list[str] | None, str | None]]) -> None:
    from psycopg.types.json import Jsonb  # noqa: PLC0415

    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn, conn.cursor() as cur:
        for row_id, imgs, image_hash in results:
            if imgs is None:
                continue
            if imgs:
                cur.execute(
                    f"update public.{AUTO_TABLE} set image_urls = %s, "
                    f"image_hash = coalesce(image_hash, %s) where id = %s",
                    (Jsonb(imgs), image_hash, row_id),
                )
            else:
                cur.execute(f"update public.{AUTO_TABLE} set raw_image_urls = '[]'::jsonb where id = %s",
                            (row_id,))


async def fill_missing_car_photos(limit: int = AUTO_BATCH) -> dict[str, int]:
    """Un lotto: la prima foto delle auto che non ne hanno, dalle più recenti."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column(AUTO_TABLE, "raw_image_urls") or time.monotonic() < _auto_state["paused_until"]:
        return {"done": 0}

    def queue() -> list[dict[str, Any]]:
        with _get_pool().connection() as conn:
            return [dict(r) for r in conn.execute(
                f"""select id, listing_url, raw_image_urls, image_urls from public.{AUTO_TABLE}
                    where image_urls = '[]'::jsonb and raw_image_urls is not null
                      and raw_image_urls <> '[]'::jsonb and status in ('nuovo', 'visto')
                      and not (id::text = any(%s))
                    order by found_at desc limit %s""",
                (list(_auto_state["skip"]), limit),
            ).fetchall()]

    rows = await asyncio.to_thread(queue)
    if not rows:
        return {"done": 0}
    results = await _download_rows(rows, _auto_state, first_only=True)
    await asyncio.to_thread(_save_auto, results)
    done = sum(1 for _, imgs, _ in results if imgs)
    logger.info("Foto auto: prima foto per %d/%d auto", done, len(results))
    return {"done": done}


async def complete_car_galleries(limit: int = AUTO_GALLERY_BATCH) -> dict[str, int]:
    """Galleria completa per le auto che contano: salvate, in pipeline, o
    segnalate come affare (sent_alerts)."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column(AUTO_TABLE, "raw_image_urls") or time.monotonic() < _auto_state["paused_until"]:
        return {"done": 0}

    def queue() -> list[dict[str, Any]]:
        with _get_pool().connection() as conn:
            rows = conn.execute(
                f"""select a.id, a.listing_url, a.raw_image_urls, a.image_urls
                    from public.{AUTO_TABLE} a
                    where a.status in ('nuovo', 'visto')
                      and jsonb_array_length(coalesce(a.raw_image_urls, '[]'::jsonb)) > 1
                      and (a.triage = 'salvato'
                           or exists (select 1 from public.deals d where d.listing_id = a.id)
                           or exists (select 1 from public.sent_alerts s where s.listing_id = a.id))
                    limit %s""",
                (limit * 5,),
            ).fetchall()
        # Solo chi ha ancora foto remote (link a Subito) nella galleria.
        return [dict(r) for r in rows
                if any("sbito.it" in str(u) for u in (r["image_urls"] or []))
                or not r["image_urls"]][:limit]

    rows = await asyncio.to_thread(queue)
    if not rows:
        return {"done": 0}
    results = await _download_rows(rows, _auto_state, first_only=False)
    await asyncio.to_thread(_save_auto, results)
    done = sum(1 for _, imgs, _ in results if imgs)
    logger.info("Foto auto: galleria completa per %d/%d occasioni", done, len(results))
    return {"done": done}
