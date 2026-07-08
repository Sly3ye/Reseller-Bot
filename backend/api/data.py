from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.services import get_market_intelligence, list_opportunities

router = APIRouter(prefix="/api", tags=["data"])

Category = Literal["smartphone", "auto"]


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
