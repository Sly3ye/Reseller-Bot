from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services import get_market_intelligence, list_opportunities
from backend.services.reads import _opportunities_table

router = APIRouter(prefix="/api", tags=["data"])

Category = Literal["smartphone", "auto", "automobile"]


@router.get("/opportunities")
async def get_opportunities(
    category: Category = Query(default="smartphone"),
    limit: int = Query(default=60, ge=1, le=200),
) -> list[dict]:
    """Live Sniper feed for a vertical (category), newest first."""
    try:
        return list_opportunities(category=category, limit=limit)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/trends")
async def get_trends(
    category: Category = Query(default="smartphone"),
) -> dict:
    """Market Intelligence: KPIs, price trend series and per-model stats."""
    try:
        return get_market_intelligence(category=category)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class OpportunityPatch(BaseModel):
    status: Literal["nuovo", "visto", "scaduto", "venduto_rimosso"]


@router.patch("/opportunities/{opportunity_id}")
async def patch_opportunity(
    opportunity_id: str,
    payload: OpportunityPatch,
    category: Category = Query(default="smartphone"),
) -> dict:
    """Aggiorna lo stato di un'opportunità (es. 'visto' quando la apri)."""
    from backend.core.database import get_db

    table = _opportunities_table(category)
    try:
        updated = (
            get_db()
            .table(table)
            .update({"status": payload.status})
            .eq("id", opportunity_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not updated.data:
        raise HTTPException(status_code=404, detail="Opportunità non trovata.")
    return updated.data[0]
