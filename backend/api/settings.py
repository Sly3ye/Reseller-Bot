"""API impostazioni configurabili da UI (soglie alert, margine, ricambi Apple)."""

from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from backend.services import settings_store

router = APIRouter(prefix="/api", tags=["settings"])


@router.get("/settings")
async def get_settings() -> dict[str, Any]:
    """Impostazioni effettive (default + override salvati)."""
    try:
        return settings_store.get_all()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


class SettingsPatch(BaseModel):
    # Sottoinsieme di chiavi note; le sconosciute sono ignorate lato store.
    values: dict[str, Any]


@router.put("/settings")
async def put_settings(payload: SettingsPatch) -> dict[str, Any]:
    """Salva gli override (solo chiavi note) e ritorna le impostazioni aggiornate."""
    try:
        return settings_store.update(payload.values)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
