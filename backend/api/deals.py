"""Pipeline P&L — il gestionale degli affari (tabella ``deals``).

Ciclo di vita: interessante → contattato → offerta → comprato → in_vendita →
venduto (oppure sfumato). Ogni deal registra prezzi e costi reali: il profitto
NETTO calcolato qui è la verità contabile dell'impresa e il termine di
paragone per la qualità delle stime del bot.
"""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.core.database import get_db

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


def _shape_deal(row: dict[str, Any]) -> dict[str, Any]:
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

    return {
        **row,
        "invested": invested,
        "extraCostsTotal": costs or 0,
        "profit": profit,
        "realMarginPct": margin_pct,
        "estimatedMarginEur": estimated,
    }


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
    return [_shape_deal(row) for row in rows]


@router.get("/summary")
async def deals_summary() -> dict:
    """KPI P&L: capitale investito, profitto realizzato, margine medio reale."""
    db = get_db()
    try:
        rows = db.table("deals").select("*").limit(1000).execute().data or []
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    shaped = [_shape_deal(row) for row in rows]
    sold = [d for d in shaped if d["stage"] == "venduto" and d["profit"] is not None]
    open_deals = [
        d for d in shaped if d["stage"] in ("comprato", "in_vendita")
    ]

    realized = sum(d["profit"] for d in sold)
    invested_open = sum(d["invested"] or 0 for d in open_deals)
    margins = [d["realMarginPct"] for d in sold if d["realMarginPct"] is not None]

    return {
        "totalDeals": len(shaped),
        "sold": len(sold),
        "openDeals": len(open_deals),
        "investedOpen": round(invested_open, 2),
        "realizedProfit": round(realized, 2),
        "avgRealMarginPct": round(sum(margins) / len(margins), 1) if margins else None,
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
