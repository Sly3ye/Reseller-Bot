from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.tasks import run_nightly_batch, scrape_subito_and_save

router = APIRouter(prefix="/api/scrape", tags=["scrape"])


@router.get("/test-subito")
async def test_subito_scrape(
    query: str = Query(default="iPhone 13 Pro", min_length=2),
    category: Literal["smartphone", "auto", "automobile"] = "smartphone",
    pages: int = Query(default=1, ge=1, le=2),
) -> dict:
    try:
        return await scrape_subito_and_save(
            query=query,
            category=category,
            pages=pages,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/run-nightly")
async def run_nightly(
    query: str = Query(default="iPhone 13 Pro", min_length=2),
    category: Literal["smartphone", "auto", "automobile"] = "smartphone",
    max_results: int = Query(default=50, ge=5, le=100),
) -> dict:
    """Motore Notturno: calcola la media di mercato e salva in market_trends."""
    try:
        return await run_nightly_batch(
            query=query,
            category=category,
            max_results=max_results,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
