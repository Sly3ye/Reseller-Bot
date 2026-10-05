"""Allarmi di deriva del formato (Goal Version §2.3).

Se Subito cambia un campo (``/car``, ``geo``, ``dates``, immagini) il parsing
produce valori vuoti in silenzio e ce ne si accorge settimane dopo, da
statistiche strane. Ogni ora: quota di annunci con il campo pieno fra gli
ultimi arrivati contro una base (gli annunci arrivati fino a 24 ore prima).
Se un campo che di solito c'è (base ≥ 50%) scende sotto i 3/4 della base,
parte un allarme alla chat ops; un altro quando rientra. Lo stato sta in
``app_settings`` (``drift_state:<categoria>``): lo legge il cruscotto e
impedisce di ripetere lo stesso allarme ogni ora.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

TABLES = {"smartphone": "live_opportunities_tech", "automobile": "live_opportunities_auto"}
_PHOTOS = "jsonb_array_length(coalesce(raw_image_urls, '[]'::jsonb)) > 0"
FIELDS: dict[str, dict[str, str]] = {
    "smartphone": {
        "dataPubblicazione": "published_at is not null",
        "foto": _PHOTOS,
        "venditore": "seller_id is not null",
        "tipoVenditore": "seller_type is not null",
        "prezzo": "asking_price > 0",
        "memoria": "storage_gb is not null",
        "provincia": "province is not null",
    },
    "automobile": {
        "dataPubblicazione": "published_at is not null",
        "foto": _PHOTOS,
        "venditore": "seller_id is not null",
        "prezzo": "asking_price > 0",
        "datiStrutturati": "car_model is not null",
        "potenza": "power_kw is not null",
        "anno": "year is not null",
        "km": "km is not null",
        "carburante": "fuel is not null",
        "immatricolazione": "register_month is not null",
        "provincia": "province is not null",
    },
}
RECENT_N = 300
BASE_N = 3000
MIN_RECENT = 100      # sotto, troppo pochi annunci nuovi per giudicare
MIN_BASE = 0.5        # campi che di solito mancano: nessun allarme
DROP_RATIO = 0.75     # allarme sotto i 3/4 della base


def evaluate(recent: dict[str, float | None], base: dict[str, float | None]) -> dict[str, dict[str, float]]:
    """Campi in allarme: {campo: {recent, base}} (quote 0–1)."""
    alarms: dict[str, dict[str, float]] = {}
    for field, b in base.items():
        r = recent.get(field)
        if b is None or r is None:
            continue
        if b >= MIN_BASE and r < b * DROP_RATIO:
            alarms[field] = {"recent": round(r, 3), "base": round(b, 3)}
    return alarms


def _measure(category: str) -> dict[str, Any] | None:
    from backend.core.database import _get_pool  # noqa: PLC0415

    table, fields = TABLES[category], FIELDS[category]
    cols = ", ".join(f"avg(({cond})::int) as \"{name}\"" for name, cond in fields.items())

    def sql(base_where: str, base_offset: int) -> str:
        return f"""
            with recent as (
              select * from public.{table}
              where status in ('nuovo', 'visto') and found_at > now() - interval '24 hours'
              order by found_at desc limit {RECENT_N}
            ), base as (
              select * from public.{table}
              where status in ('nuovo', 'visto') {base_where}
              order by found_at desc offset {base_offset} limit {BASE_N}
            )
            select 'recent' as w, count(*) as n, {cols} from recent
            union all
            select 'base' as w, count(*) as n, {cols} from base
        """

    with _get_pool().connection() as conn:
        # Base = arrivati fino a 24 ore prima: una deriva resta in allarme per
        # almeno un giorno. Primo giorno di raccolta (base troppo piccola):
        # gli annunci subito prima dei recenti.
        rows = {r["w"]: r for r in conn.execute(
            sql("and found_at <= now() - interval '24 hours'", 0)).fetchall()}
        if (rows.get("base") or {}).get("n", 0) < MIN_RECENT:
            rows = {r["w"]: r for r in conn.execute(sql("", RECENT_N)).fetchall()}
    recent, base = rows.get("recent"), rows.get("base")
    if not recent or not base or recent["n"] < MIN_RECENT or base["n"] < MIN_RECENT:
        return None

    def shares(row: dict[str, Any]) -> dict[str, float | None]:
        return {k: (float(row[k]) if row[k] is not None else None) for k in fields}

    return {"recentN": recent["n"], "baseN": base["n"], "recent": shares(recent), "base": shares(base)}


def _pct(x: float) -> str:
    return f"{x * 100:.0f}%"


async def drift_check() -> dict[str, Any]:
    """Giro orario: misura, confronta con lo stato precedente, allerta sulle
    transizioni (campo nuovo in allarme, campo rientrato)."""
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.services.notifications import notify_system_alert  # noqa: PLC0415
    from backend.services.sweep import _load_state, _save_state  # noqa: PLC0415

    db = get_db()
    out: dict[str, Any] = {}
    now = datetime.now(timezone.utc).isoformat()
    for category in TABLES:
        try:
            measured = await asyncio.to_thread(_measure, category)
        except Exception:
            logger.exception("Deriva %s: misura fallita", category)
            continue
        if measured is None:
            continue
        alarms = evaluate(measured["recent"], measured["base"])
        prev = (await asyncio.to_thread(_load_state, db, f"drift_state:{category}")).get("alarms") or {}
        for field, values in alarms.items():
            values["since"] = (prev.get(field) or {}).get("since") or now
        new, cleared = set(alarms) - set(prev), set(prev) - set(alarms)
        if new:
            lines = ", ".join(f"{f} {_pct(alarms[f]['recent'])} (di solito {_pct(alarms[f]['base'])})"
                              for f in sorted(new))
            logger.warning("Deriva del formato %s: %s", category, lines)
            await notify_system_alert(
                f"🟠 <b>Deriva dati {category}</b>: campi che si svuotano negli ultimi "
                f"{measured['recentN']} annunci: {lines}. Subito ha cambiato il formato?")
        if cleared:
            await notify_system_alert(f"✅ <b>Dati {category}</b>: rientrati {', '.join(sorted(cleared))}")
        state = {"at": now, "alarms": alarms, "recentN": measured["recentN"], "baseN": measured["baseN"],
                 "recent": {k: round(v, 3) for k, v in measured["recent"].items() if v is not None}}
        await asyncio.to_thread(_save_state, db, f"drift_state:{category}", state)
        out[category] = state
    return out


def drift_state(category: str) -> dict[str, Any] | None:
    """Ultimo esito per il cruscotto."""
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.services.sweep import _load_state  # noqa: PLC0415

    return _load_state(get_db(), f"drift_state:{category}") or None
