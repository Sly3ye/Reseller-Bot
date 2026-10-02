"""Stato dei backup (F2): legge l'esito scritto dal servizio `backup` del
docker-compose (``scripts/backup_loop.sh``) in ``/backups/last_backup.json``.

- ``get_backup_status()``: per il cruscotto Qualità del dato;
- ``check_backup()``: job giornaliero, allarme Telegram se l'ultimo backup è
  fallito o se il più recente riuscito ha più di ``STALE_HOURS`` ore.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

STATUS_FILE = Path(os.getenv("BACKUP_STATUS_FILE", "/backups/last_backup.json"))
# Backup ogni 24h (o appena il PC si riaccende): oltre 36h qualcosa non va.
STALE_HOURS = 36


def get_backup_status() -> dict[str, Any]:
    """Esito dell'ultimo giro + età dell'ultimo backup riuscito.

    ``state``: "ok" · "fallito" · "vecchio" · "assente" (servizio mai partito
    o cartella non montata)."""
    try:
        raw = json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"state": "assente"}
    except (OSError, ValueError) as exc:
        return {"state": "fallito", "error": f"esito illeggibile: {exc}"}

    last_ok = raw.get("lastOkEpoch")
    age_h = (
        round((datetime.now(timezone.utc).timestamp() - float(last_ok)) / 3600, 1)
        if last_ok else None
    )
    if not raw.get("ok"):
        state = "fallito"
    elif age_h is None or age_h > STALE_HOURS:
        state = "vecchio"
    else:
        state = "ok"
    tables = raw.get("tables") or {}
    tech = tables.get("live_opportunities_tech") or {}
    return {
        "state": state,
        "at": raw.get("at"),
        "error": raw.get("error") or None,
        "file": raw.get("file"),
        "sizeKb": raw.get("sizeKb"),
        "lastOkAgeHours": age_h,
        "restoredListings": tech.get("restored"),
        "media": raw.get("media"),
        "retentionDays": raw.get("retentionDays"),
    }


async def check_backup() -> dict[str, Any]:
    """Allarme se il backup non è sano (una volta al giorno, dal scheduler)."""
    from backend.services.notifications import notify_system_alert  # noqa: PLC0415

    status = get_backup_status()
    if status["state"] in ("fallito", "vecchio", "assente"):
        detail = {
            "fallito": f"ultimo giro fallito: {status.get('error')}",
            "vecchio": f"ultimo backup riuscito {status.get('lastOkAgeHours')} ore fa",
            "assente": "nessun esito: il servizio `backup` del docker-compose gira?",
        }[status["state"]]
        logger.warning("Backup non sano: %s", detail)
        try:
            await notify_system_alert(f"🟠 <b>Backup</b> — {detail}")
        except Exception:
            logger.exception("Alert di sistema (backup) fallito")
    return status
