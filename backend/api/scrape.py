from typing import Literal

from fastapi import APIRouter, HTTPException, Query

from backend.tasks import scrape_subito_and_save

router = APIRouter(prefix="/api/scrape", tags=["scrape"])


@router.get("/test-subito")
async def test_subito_scrape(
    query: str = Query(default="iPhone 13 Pro", min_length=2),
    category: Literal["smartphone", "auto"] = "smartphone",
    max_results: int = Query(default=5, ge=1, le=5),
) -> dict:
    try:
        return await scrape_subito_and_save(
            query=query,
            category=category,
            max_results=max_results,
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
