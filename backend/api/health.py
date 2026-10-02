from fastapi import APIRouter

from backend.services.health import get_health

router = APIRouter(prefix="/health", tags=["health"])


@router.get("")
async def health_check() -> dict[str, str]:
    """Liveness minimale (per probe/uptime)."""
    return {"status": "ok"}


@router.get("/scraper")
async def scraper_health() -> dict:
    """Salute dello scraper: ultimo giro per categoria, proxy, impersonation.

    Utile per accorgersi se la raccolta si è bloccata (status 'down').
    """
    return get_health()


@router.get("/data-quality")
async def data_quality(category: str = "smartphone") -> dict:
    """Qualità del dato: copertura vs Subito, completezza dei campi, raccolta
    delle ultime 24h. Dice quanto fidarsi delle metriche."""
    from backend.services.data_quality import get_data_quality  # noqa: PLC0415

    return get_data_quality(category)
