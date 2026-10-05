"""Budget di richieste dallo stesso IP (Goal Version §2.2): quanto consuma
ogni lavoro. Il pacer conta per job (``subito.current_job``); qui si
accumula in ``request_log`` (giorno × job, migrazione 25) e si legge per il
cruscotto. È il primo pezzo del governatore: prima si misura, poi si
mettono quote e priorità.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

logger = logging.getLogger(__name__)


def flush_request_counts() -> dict[str, list[int]]:
    """Scrive i conteggi accumulati in request_log (somma sul giorno)."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415
    from backend.scrapers.subito import take_request_counts  # noqa: PLC0415

    counts = take_request_counts()
    if not counts:
        return {}
    try:
        if not has_column("request_log", "requests"):
            return counts
        with _get_pool().connection() as conn, conn.cursor() as cur:
            for job, (req, blocks) in counts.items():
                cur.execute(
                    "insert into public.request_log (day, job, requests, blocks) values (%s, %s, %s, %s) "
                    "on conflict (day, job) do update set requests = request_log.requests + excluded.requests, "
                    "blocks = request_log.blocks + excluded.blocks",
                    (date.today(), job, req, blocks),
                )
    except Exception:
        logger.exception("request_log non aggiornato")
    return counts


def requests_today() -> dict[str, Any]:
    """Richieste e blocchi di oggi per job, più il totale."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column("request_log", "requests"):
        return {}
    with _get_pool().connection() as conn:
        rows = conn.execute(
            "select job, requests, blocks from public.request_log where day = current_date order by requests desc"
        ).fetchall()
    jobs = {r["job"]: {"requests": r["requests"], "blocks": r["blocks"]} for r in rows}
    return {"jobs": jobs, "total": sum(j["requests"] for j in jobs.values()),
            "blocks": sum(j["blocks"] for j in jobs.values())}
