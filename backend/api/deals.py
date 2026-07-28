"""Pipeline P&L — il gestionale degli affari (tabella ``deals``).

Ciclo di vita: interessante → contattato → offerta → comprato → in_vendita →
venduto (oppure sfumato). Ogni deal registra prezzi e costi reali: il profitto
NETTO calcolato qui è la verità contabile dell'impresa e il termine di
paragone per la qualità delle stime del bot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.database import get_db


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None

router = APIRouter(prefix="/api/deals", tags=["deals"])

Stage = Literal[
    "interessante", "contattato", "offerta", "comprato",
    "in_vendita", "venduto", "sfumato",
]


class DealCreate(BaseModel):
    category: Literal["smartphone", "automobile"]
    listing_id: str | None = None
    title: str | None = None
    listing_url: str | None = None
    stage: Stage = "interessante"
    asking_price: float | None = None
    market_avg: float | None = None
    offer_price: float | None = None
    notes: str | None = None


class DealUpdate(BaseModel):
    stage: Stage | None = None
    offer_price: float | None = None
    buy_price: float | None = None
    sell_price: float | None = None
    extra_costs: list[dict[str, Any]] | None = Field(
        default=None, description='[{"label": "batteria", "amount": 79}]'
    )
    notes: str | None = None


# Da quanti giorni un affare può restare fermo in uno stadio prima che sia un
# problema. Non sono numeri sacri: sono la soglia oltre la quale un pezzo smette
# di essere un affare e diventa capitale immobilizzato che si deprezza.
_STALE_AFTER_DAYS: dict[str, int] = {
    "interessante": 7,    # o lo contatti o lo lasci andare
    "contattato": 5,      # trattativa che non si muove
    "offerta": 5,         # offerta senza risposta
    "comprato": 14,       # comprato e non ancora messo in vendita: soldi fermi
    "in_vendita": 30,     # invenduto: il prezzo è fuori mercato
}

_STALE_HINTS: dict[str, str] = {
    "interessante": "fermo qui: contattalo o scartalo",
    "contattato": "nessuna risposta: rilancia o passa oltre",
    "offerta": "offerta senza esito: chiudi o ritira",
    "comprato": "comprato e non ancora in vendita: capitale fermo",
    "in_vendita": "invenduto da troppo: il prezzo è fuori mercato",
}


def _staleness(
    stage: str, days_in_stage: int | None, carry_month_eur: int | None
) -> dict[str, Any] | None:
    """Allerta sui deal fermi: da quanto, quanto è grave, quanto sta costando.

    ``carry_month_eur`` = deprezzamento mensile della variante (curva di
    deprezzamento): trasforma "è fermo da 40 giorni" in "ti è già costato 33€",
    che è l'unica formulazione che fa agire.
    """
    limit = _STALE_AFTER_DAYS.get(stage)
    if limit is None or days_in_stage is None or days_in_stage < limit:
        return None
    return {
        "days": days_in_stage,
        "limit": limit,
        # Oltre il doppio della soglia non è più un ritardo, è un problema.
        "level": "critico" if days_in_stage >= limit * 2 else "attenzione",
        "hint": _STALE_HINTS.get(stage, "fermo da troppo tempo"),
        # Solo per gli stadi in cui il pezzo è già tuo: il deprezzamento corre.
        "carryLossEur": (
            round(carry_month_eur * days_in_stage / 30)
            if carry_month_eur and stage in ("comprato", "in_vendita")
            else None
        ),
    }


def _shape_deal(
    row: dict[str, Any], carry_month_eur: int | None = None
) -> dict[str, Any]:
    """Aggiunge i campi calcolati: investito, profitto netto, margine reale."""
    buy = float(row["buy_price"]) if row.get("buy_price") is not None else None
    sell = float(row["sell_price"]) if row.get("sell_price") is not None else None
    costs = sum(
        float(c.get("amount") or 0) for c in (row.get("extra_costs") or [])
    )

    invested = (buy + costs) if buy is not None else None
    profit = (sell - invested) if (sell is not None and invested) else None
    margin_pct = (
        round(profit / invested * 100, 1) if profit is not None and invested else None
    )

    # Margine stimato dal bot al momento dell'aggancio (per il confronto
    # stima vs realtà una volta chiuso l'affare).
    asking = float(row["asking_price"]) if row.get("asking_price") is not None else None
    avg = float(row["market_avg"]) if row.get("market_avg") is not None else None
    estimated = round(avg - asking, 2) if (avg is not None and asking) else None

    # Feedback loop: quanto il profitto reale si scosta dalla stima del bot.
    estimate_error = (
        round(profit - estimated, 2)
        if (profit is not None and estimated is not None)
        else None
    )

    # Giorni di detenzione (proxy: dall'aggancio alla vendita) e ROI/giorno reale.
    held_days: int | None = None
    roi_per_day: float | None = None
    if row.get("stage") == "venduto":
        created = _parse_ts(row.get("created_at"))
        sold_at = _parse_ts(row.get("updated_at"))
        if created and sold_at:
            held_days = max(0, (sold_at - created).days)
        if margin_pct is not None and held_days and held_days > 0:
            roi_per_day = round(margin_pct / held_days, 2)

    # Tempo-in-stadio: ``updated_at`` cambia a ogni passaggio di stadio, quindi
    # è il proxy giusto per "da quanto è fermo QUI" (diverso dall'età del deal).
    stage = str(row.get("stage") or "")
    now = datetime.now(timezone.utc)
    last_move = _parse_ts(row.get("updated_at"))
    created = _parse_ts(row.get("created_at"))
    days_in_stage = max(0, (now - last_move).days) if last_move else None
    age_days = max(0, (now - created).days) if created else None

    return {
        **row,
        "daysInStage": days_in_stage,
        "ageDays": age_days,
        "stale": (
            _staleness(stage, days_in_stage, carry_month_eur)
            if stage not in ("venduto", "sfumato")
            else None
        ),
        "invested": invested,
        "extraCostsTotal": costs or 0,
        "profit": profit,
        "realMarginPct": margin_pct,
        "estimatedMarginEur": estimated,
        "estimateErrorEur": estimate_error,
        "heldDays": held_days,
        "roiPerDayPct": roi_per_day,
    }


def _carry_by_deal(db: Any, rows: list[dict[str, Any]]) -> dict[str, int]:
    """{deal_id: € persi al mese} risalendo alla variante dell'annuncio agganciato.

    Serve a dire "questo pezzo fermo ti è già costato X€" invece del solo numero
    di giorni. I deal senza ``listing_id`` (inseriti a mano) restano senza:
    nessuna variante, nessuna curva, nessun numero inventato.
    """
    from backend.services.depreciation import carry_cost_by_variant
    from backend.services.reads import _opportunities_table, _variant_price_pools

    wanted = {
        str(r["listing_id"]): str(r["id"])
        for r in rows
        if r.get("listing_id") and r.get("category") != "automobile"
    }
    if not wanted:
        return {}

    table = _opportunities_table("smartphone")
    try:
        listings = (
            db.table(table)
            .select("id, variant_key")
            .in_("id", list(wanted))
            .execute()
            .data
            or []
        )
    except Exception:
        return {}

    carry = carry_cost_by_variant(_variant_price_pools(db, table))
    out: dict[str, int] = {}
    for listing in listings:
        month = carry.get(listing.get("variant_key"))
        if month:
            out[wanted[str(listing["id"])]] = month
    return out


@router.get("")
async def list_deals(stage: Stage | None = None) -> list[dict]:
    db = get_db()
    try:
        query = db.table("deals").select("*").order("updated_at", desc=True)
        if stage:
            query = query.eq("stage", stage)
        rows = query.limit(200).execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    carry = _carry_by_deal(db, rows)
    return [_shape_deal(row, carry.get(str(row["id"]))) for row in rows]


@router.get("/summary")
async def deals_summary() -> dict:
    """KPI P&L: capitale investito, profitto realizzato, margine medio reale."""
    db = get_db()
    try:
        rows = db.table("deals").select("*").limit(1000).execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    carry = _carry_by_deal(db, rows)
    shaped = [_shape_deal(row, carry.get(str(row["id"]))) for row in rows]
    sold = [d for d in shaped if d["stage"] == "venduto" and d["profit"] is not None]
    open_deals = [
        d for d in shaped if d["stage"] in ("comprato", "in_vendita")
    ]

    realized = sum(d["profit"] for d in sold)
    invested_open = sum(d["invested"] or 0 for d in open_deals)
    margins = [d["realMarginPct"] for d in sold if d["realMarginPct"] is not None]

    # Feedback loop: stima del bot vs realtà sui venduti.
    paired = [
        (d["estimatedMarginEur"], d["profit"])
        for d in sold
        if d["estimatedMarginEur"] is not None and d["profit"] is not None
    ]
    est_bias = (
        round(sum(p - e for e, p in paired) / len(paired), 2) if paired else None
    )
    avg_est = round(sum(e for e, _ in paired) / len(paired), 2) if paired else None
    avg_real = round(sum(p for _, p in paired) / len(paired), 2) if paired else None
    # Accuratezza: 100 − errore medio relativo (|reale−stima| / |stima|), clampata.
    accuracy = None
    if paired:
        rel = [abs(p - e) / abs(e) for e, p in paired if e]
        if rel:
            accuracy = round(max(0.0, 100 - sum(rel) / len(rel) * 100), 1)

    held = [d["heldDays"] for d in sold if d.get("heldDays") is not None]
    roi_days = [d["roiPerDayPct"] for d in sold if d.get("roiPerDayPct") is not None]

    # Affari fermi oltre soglia e quanto sta costando tenerli (deprezzamento
    # maturato sui pezzi già acquistati).
    stale = [d for d in shaped if d.get("stale")]
    stale_loss = sum(d["stale"].get("carryLossEur") or 0 for d in stale)

    return {
        "staleDeals": len(stale),
        "staleCriticalDeals": len([d for d in stale if d["stale"]["level"] == "critico"]),
        "staleCarryLossEur": stale_loss or None,
        "totalDeals": len(shaped),
        "sold": len(sold),
        "openDeals": len(open_deals),
        "investedOpen": round(invested_open, 2),
        "realizedProfit": round(realized, 2),
        "avgRealMarginPct": round(sum(margins) / len(margins), 1) if margins else None,
        # Feedback loop stima vs realtà.
        "avgEstimatedMarginEur": avg_est,
        "avgRealizedProfitEur": avg_real,
        "estimationBiasEur": est_bias,
        "estimationAccuracyPct": accuracy,
        "avgHeldDays": round(sum(held) / len(held), 1) if held else None,
        "realizedRoiPerDayPct": round(sum(roi_days) / len(roi_days), 2) if roi_days else None,
    }


@router.post("", status_code=201)
async def create_deal(payload: DealCreate) -> dict:
    db = get_db()
    try:
        created = (
            db.table("deals")
            .insert(payload.model_dump(exclude_none=True))
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not created.data:
        raise HTTPException(status_code=500, detail="Insert non riuscito.")
    return _shape_deal(created.data[0])


@router.patch("/{deal_id}")
async def update_deal(deal_id: str, payload: DealUpdate) -> dict:
    patch = payload.model_dump(exclude_none=True)
    if not patch:
        raise HTTPException(status_code=422, detail="Nessun campo da aggiornare.")
    db = get_db()
    try:
        updated = db.table("deals").update(patch).eq("id", deal_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not updated.data:
        raise HTTPException(status_code=404, detail="Deal non trovato.")
    return _shape_deal(updated.data[0])


@router.delete("/{deal_id}", status_code=204)
async def delete_deal(deal_id: str) -> None:
    db = get_db()
    try:
        db.table("deals").delete().eq("id", deal_id).execute()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
