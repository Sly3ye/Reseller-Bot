"""Obiettivi della Goal Version misurati dal vivo (docs/GOAL-VERSION.md, "Come
si sa che ci siamo"): a che punto siamo in un colpo d'occhio, invece di
ricostruirlo da cinque pannelli.

Ogni obiettivo: valore misurato, soglia, ``ok`` = True (raggiunto), False
(no) o None (non ancora misurabile: pochi dati, Telegram spento...). La
valutazione è una funzione pura (``evaluate_goals``) → testabile.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

# Affari chiusi con stima prima di giudicare l'errore stima ↔ realizzo.
MIN_CLOSED_FOR_ERROR = 30


def _parse(ts: Any) -> datetime | None:
    if isinstance(ts, datetime):
        return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def evaluate_goals(dq: dict[str, Any], deals: list[dict[str, Any]],
                   now: datetime | None = None) -> list[dict[str, Any]]:
    """dq = Qualità del dato (iPhone), deals = affari già calcolati
    (``api.deals._shape_deal``: profit, estimatedMarginEur, stage, updated_at)."""
    now = now or datetime.now(timezone.utc)
    goals: list[dict[str, Any]] = []

    lat = dq.get("latency") or {}
    p95 = lat.get("alertP95Min")
    goals.append({
        "key": "latenza", "label": "Scoperta → alert (p95)", "target": "≤ 2 min",
        "value": f"{p95} min" if p95 is not None else None,
        "ok": (p95 <= 2) if p95 is not None else None,
        "detail": (f"{lat.get('alerts7d') or 0} affari segnalati in 7 giorni; pubblicazione → scoperta "
                   f"mediana {lat.get('discoveryP50Min')} min (comprende ~6 min di indicizzazione di Subito)"),
    })

    delivery = dq.get("alertDelivery7d") or {}
    failed, sent, not_sent = delivery.get("failed"), delivery.get("delivered") or 0, delivery.get("not_sent") or 0
    goals.append({
        "key": "falliti", "label": "Alert falliti (7 giorni)", "target": "0",
        "value": failed,
        # Senza nessun invio tentato non si può dire che siano zero.
        "ok": (failed == 0) if failed is not None and (sent or failed) else None,
        "detail": f"{sent} consegnati" + (f", {not_sent} registrati senza Telegram" if not_sent else ""),
    })

    sold = [d for d in deals if d.get("stage") == "venduto" and d.get("profit") is not None]
    week = [d for d in sold if (_parse(d.get("updated_at")) or now) >= now - timedelta(days=7)]
    goals.append({
        "key": "affari", "label": "Affari chiusi (ultimi 7 giorni)", "target": "≥ 1",
        "value": len(week), "ok": len(week) >= 1,
        "detail": f"{len(sold)} chiusi in tutto, {sum(1 for d in deals if d.get('stage') not in ('venduto', 'sfumato'))} aperti",
    })

    paired = [(float(d["estimatedMarginEur"]), float(d["profit"])) for d in sold
              if d.get("estimatedMarginEur") not in (None, 0)]
    err = (sum(abs(p - e) / abs(e) for e, p in paired) / len(paired) * 100) if paired else None
    goals.append({
        "key": "stima", "label": "Errore stima ↔ realizzo", "target": f"≤ 10% su {MIN_CLOSED_FOR_ERROR} affari",
        "value": f"{err:.0f}%" if err is not None else None,
        "ok": (err <= 10) if err is not None and len(paired) >= MIN_CLOSED_FOR_ERROR else None,
        "detail": f"{len(paired)}/{MIN_CLOSED_FOR_ERROR} affari chiusi con la stima del bot",
    })

    cov = dq.get("coverage") or {}
    seen = cov.get("seenPct")
    goals.append({
        "key": "copertura", "label": "Copertura dell'inventario iPhone", "target": "≥ 95%",
        "value": f"{seen}%" if seen is not None else None,
        "ok": (seen >= 95) if seen is not None else None,
        "detail": (f"ultimo inventario {cov.get('inventoryAt')[:16].replace('T', ' ')}"
                   if cov.get("inventoryAt") else "nessun inventario completo"),
    })
    return goals


def goal_scoreboard() -> dict[str, Any]:
    """Obiettivi con i dati veri (endpoint /health/goals)."""
    from backend.api.deals import _shape_deal  # noqa: PLC0415
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.services.data_quality import get_data_quality  # noqa: PLC0415

    dq = get_data_quality("smartphone")
    try:
        rows = get_db().table("deals").select("*").execute().data or []
    except Exception:
        rows = []
    deals = [_shape_deal(r) for r in rows]
    goals = evaluate_goals(dq, deals)
    return {"at": datetime.now(timezone.utc).isoformat(), "goals": goals,
            "met": sum(1 for g in goals if g["ok"] is True), "total": len(goals)}
