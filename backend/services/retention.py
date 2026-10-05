"""Conservazione dei dati (Goal Version §2.6).

Degli annunci spariti (venduti o scaduti) da più di ``RETENTION_DAYS`` giorni
si tengono prezzi, date, modello e storia (``listing_events``), cioè ciò che
serve alle statistiche, e si cancellano descrizione e identificativo del
venditore: i dati che possono riguardare una persona e che non servono più
(principi di minimizzazione e limitazione della conservazione, GDPR art. 5,
par. 1, lett. c ed e). Contiene anche la crescita del DB: le descrizioni sono
la parte più pesante delle ~13.000 auto al giorno.

Le foto restano (scelta esplicita: si tengono tutte). ``RETENTION_DAYS=0``
spegne il lavoro.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TABLES = ("live_opportunities_tech", "live_opportunities_auto")
REMOVED = ("venduto_rimosso", "scaduto")


def retention_sql(table: str) -> str:
    """UPDATE per una tabella (il trigger di listing_events non scatta:
    descrizione e venditore non sono fra le sue colonne)."""
    return (
        f"update public.{table} set description = null, seller_id = null "
        f"where status::text = any(%s) and updated_at < now() - make_interval(days => %s) "
        f"and (description is not null or seller_id is not null)"
    )


def apply_retention(days: int | None = None) -> dict[str, Any]:
    """Un giro (schedulato ogni notte): righe alleggerite per tabella."""
    from backend.core.config import settings  # noqa: PLC0415
    from backend.core.database import _get_pool  # noqa: PLC0415

    days = settings.retention_days if days is None else days
    if not days or days <= 0:
        return {"days": 0, "updated": {}}
    updated: dict[str, int] = {}
    with _get_pool().connection() as conn:
        for table in TABLES:
            cur = conn.execute(retention_sql(table), (list(REMOVED), days))
            updated[table] = cur.rowcount
    if any(updated.values()):
        logger.info("Conservazione (%d giorni): descrizione e venditore tolti da %s", days, updated)
    return {"days": days, "updated": updated}
