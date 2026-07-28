from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from backend.services import (
    get_market_intelligence,
    get_time_to_sale,
    list_opportunities,
)
from backend.services.reads import _opportunities_table

router = APIRouter(prefix="/api", tags=["data"])

Category = Literal["smartphone", "auto", "automobile"]


Sort = Literal["score", "recent", "margin", "roi"]
View = Literal["attivi", "salvati", "tutti"]
Preset = Literal["compra_ora", "motivati", "riparabili"]


@router.get("/opportunities")
async def get_opportunities(
    category: Category = Query(default="smartphone"),
    sort: Sort = Query(default="score"),
    model: str | None = Query(default=None, description="model_key, es. iphone-13-pro-max"),
    storage: int | None = Query(default=None),
    color: str | None = Query(default=None),
    condition: str | None = Query(default=None),
    deal_class: str | None = Query(default=None),
    min_margin: float | None = Query(default=None),
    q: str | None = Query(default=None),
    view: View = Query(default="attivi"),
    preset: Preset | None = Query(default=None),
    limit: int = Query(default=30, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> dict:
    """Feed opportunità: tutte le attive, ordinate (default Deal Score), con
    filtri, triage (salvati/scartati) e preset. Ritorna {items, total, facets}."""
    try:
        return list_opportunities(
            category=category,
            sort=sort,
            model=model,
            storage=storage,
            color=color,
            condition=condition,
            deal_class=deal_class,
            min_margin=min_margin,
            q=q,
            view=view,
            preset=preset,
            limit=limit,
            offset=offset,
        )
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


@router.get("/time-to-sale")
async def get_time_to_sale_endpoint(
    category: Category = Query(default="smartphone"),
) -> dict:
    """Tempo di vendita affettabile: fatti grezzi dei venduti (modello, colore,
    taglia, giorni, prezzo) + valori distinti. Il pivot lo fa la UI."""
    try:
        return get_time_to_sale(category=category)
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


class TriagePatch(BaseModel):
    # None = azzera (torna nel feed); 'salvato' = preferito; 'scartato' = nascondi.
    triage: Literal["salvato", "scartato"] | None


@router.patch("/opportunities/{opportunity_id}/triage")
async def patch_triage(
    opportunity_id: str,
    payload: TriagePatch,
    category: Category = Query(default="smartphone"),
) -> dict:
    """Azione utente sul feed: salva / scarta (nascondi) / azzera un annuncio."""
    from backend.core.database import get_db

    table = _opportunities_table(category)
    try:
        updated = (
            get_db()
            .table(table)
            .update({"triage": payload.triage})
            .eq("id", opportunity_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    if not updated.data:
        raise HTTPException(status_code=404, detail="Opportunità non trovata.")
    return updated.data[0]
