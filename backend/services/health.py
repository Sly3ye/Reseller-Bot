"""Salute dello scraper (Fase 3): rileva quando la raccolta si blocca.

Il rischio operativo n.1 di un bot 24/7: smettere di raccogliere in SILENZIO
(Akamai che ri-blocca, proxy morto, Subito che cambia). Qui ogni giro dello
Sniper registra il suo esito in ``scrape_runs``; se un giro passa a "down"
(tutti i target falliti o zero annunci) si manda un alert Telegram, e uno di
ripristino quando torna a funzionare — così te ne accorgi subito.

``compute_status`` è puro → testabile senza DB.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_status(targets: int, ok: int, failed: int, scraped: int) -> str:
    """Stato di un giro: ok / degraded / down / idle.

    - idle: nessun target attivo.
    - down: tutti i target hanno fallito (blocco/proxy), oppure nessun annuncio
      raccolto pur avendo target (probabile soft-block).
    - degraded: qualche target fallito ma non tutti.
    - ok: tutti i target ok e almeno un annuncio raccolto.
    """
    if targets <= 0:
        return "idle"
    if ok == 0 or scraped == 0:
        return "down"
    if failed > 0:
        return "degraded"
    return "ok"


def record_run(
    category: str,
    targets: int,
    ok: int,
    failed: int,
    scraped: int,
    new_count: int,
) -> dict[str, Any]:
    """Registra l'esito del giro e rileva le transizioni down/ripristino.

    Ritorna {status, previous, went_down, recovered}. Import DB lazy per non
    accoppiare il modulo (compute_status resta puro).
    """
    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)

    status = compute_status(targets, ok, failed, scraped)
    previous: str | None = None
    db = get_db()
    try:
        last = (
            db.table("scrape_runs")
            .select("status")
            .eq("category", category)
            .order("ran_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        previous = last[0]["status"] if last else None
        db.table("scrape_runs").insert(
            {
                "category": category,
                "status": status,
                "targets": targets,
                "ok": ok,
                "failed": failed,
                "scraped": scraped,
                "new_count": new_count,
            }
        ).execute()
    except Exception:
        logger.warning("scrape_runs non disponibile: monitoraggio salute limitato.")

    return {
        "status": status,
        "previous": previous,
        # Alert solo sulla TRANSIZIONE (evita spam a ogni giro).
        "went_down": status == "down" and previous not in (None, "down"),
        "recovered": status in ("ok", "degraded") and previous == "down",
    }


def get_health() -> dict[str, Any]:
    """Snapshot per l'endpoint /health: ultimo giro per categoria + config."""
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.core.config import settings  # noqa: PLC0415

    out: dict[str, Any] = {
        "proxy_configured": bool(settings.proxy_url),
        "impersonate_pool": settings.impersonate_pool,
        "scraper": {},
    }
    db = get_db()
    for cat in ("smartphone", "automobile"):
        try:
            last = (
                db.table("scrape_runs")
                .select("status, targets, ok, failed, scraped, new_count, ran_at")
                .eq("category", cat)
                .order("ran_at", desc=True)
                .limit(1)
                .execute()
                .data
            )
            out["scraper"][cat] = last[0] if last else None
        except Exception:
            out["scraper"][cat] = None
    return out
