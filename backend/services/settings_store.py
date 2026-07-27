"""Store impostazioni configurabili da UI (tabella app_settings).

Chiave→valore su Postgres, con i default nel codice/.env. ``get_all()`` unisce i
default con gli override salvati (cache breve) e li **applica** ai moduli che li
consumano (scoring: margine obiettivo + prezzi ricambi Apple). I consumatori
(soglie alert, chat Telegram) leggono da qui invece che dalle costanti/.env, così
si configurano dalla pagina Impostazioni senza toccare il codice.
"""

from __future__ import annotations

import copy
import threading
import time
from datetime import datetime, timezone
from typing import Any

import backend.services.scoring as scoring
from backend.core.config import settings
from backend.core.database import get_db

_TTL_SECONDS = 30.0
_lock = threading.Lock()
_cache: dict[str, Any] | None = None
_cache_at = 0.0


def _defaults() -> dict[str, Any]:
    """Valori di partenza (da .env/costanti). Copie per non mutare i moduli."""
    return {
        "alert_min_margin_pct": settings.alert_min_margin_pct,
        "alert_min_drop_pct": settings.alert_min_drop_pct,
        "alert_min_score": settings.alert_min_score,
        "target_margin_pct": copy.deepcopy(scoring.TARGET_MARGIN_PCT),
        "apple_part_eur": copy.deepcopy(scoring.APPLE_PART_EUR),
        "telegram_chat_tech": settings.telegram_chat_tech,
        "telegram_chat_auto": settings.telegram_chat_auto,
        "telegram_chat_ops": settings.telegram_chat_ops,
    }


def allowed_keys() -> set[str]:
    return set(_defaults().keys())


def _read_overrides() -> dict[str, Any]:
    try:
        rows = get_db().table("app_settings").select("key, value").execute().data or []
    except Exception:
        return {}  # tabella assente o DB giù: usa solo i default
    return {r["key"]: r["value"] for r in rows if r.get("key")}


def get_all(force: bool = False) -> dict[str, Any]:
    """Impostazioni effettive (default + override). Cache TTL breve; a ogni
    refresh riapplica margine/ricambi a scoring."""
    global _cache, _cache_at
    now = time.monotonic()
    with _lock:
        if not force and _cache is not None and now - _cache_at < _TTL_SECONDS:
            return _cache

    merged = _defaults()
    for key, value in _read_overrides().items():
        if key in merged:
            merged[key] = value

    scoring.apply_config(merged)

    with _lock:
        _cache = merged
        _cache_at = now
    return merged


def update(patch: dict[str, Any]) -> dict[str, Any]:
    """Salva gli override (solo chiavi note) e ritorna le impostazioni aggiornate."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    known = allowed_keys()
    for key, value in patch.items():
        if key not in known:
            continue
        db.table("app_settings").upsert(
            {"key": key, "value": value, "updated_at": now}, on_conflict="key"
        ).execute()
    return get_all(force=True)
