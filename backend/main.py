import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from backend.api.automations import router as automations_router
from backend.api.data import router as data_router
from backend.api.deals import router as deals_router
from backend.api.health import router as health_router
from backend.api.scrape import router as scrape_router
from backend.api.settings import router as settings_router
from backend.core.config import settings
from backend.core.migrations import apply_pending
from backend.core.scheduler import create_scheduler
from backend.services import repair_feedback

# Log applicativi visibili in `docker compose logs backend` (giri di raccolta,
# blocchi, buchi, migrazioni). Senza, si vedevano solo le righe di uvicorn.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
# httpx logga ogni singola richiesta (immagini comprese): troppo rumore.
logging.getLogger("httpx").setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# Comma-separated list of allowed frontend origins (Next.js dev server default).
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]


def _prewarm_feed() -> None:
    try:
        from backend.core.database import get_db  # noqa: PLC0415
        from backend.services.reads import _enriched_feed  # noqa: PLC0415

        _enriched_feed(get_db(), "live_opportunities_tech", "smartphone")
        logger.info("Feed iPhone pronto in cache")
    except Exception:
        logger.exception("Preparazione del feed fallita (si calcolerà alla prima richiesta)")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background scheduler with the app and stop it on shutdown."""
    # Schema allineato PRIMA che lo scheduler lavori (e che il codice controlli
    # quali colonne esistono). Un errore qui non impedisce l'avvio.
    try:
        applied = await asyncio.to_thread(apply_pending)
        if applied:
            logger.info("Migrazioni applicate all'avvio: %s", applied)
    except Exception:
        logger.exception("Migration runner fallito: schema forse non aggiornato")
    # Correzioni dalle tue riparazioni (E3) pronte prima della prima stima.
    await asyncio.to_thread(repair_feedback.refresh)
    # Feed iPhone preparato in background: valutare ~47k annunci costa ~20 s e
    # la prima apertura della dashboard non deve aspettarli. Solo nel processo
    # che serve la dashboard (il raccoglitore non la serve).
    if not settings.scheduler_enabled:
        asyncio.get_running_loop().run_in_executor(None, _prewarm_feed)
    scheduler = create_scheduler()
    app.state.scheduler = scheduler
    if settings.scheduler_enabled:
        scheduler.start()
        logger.info(
            "Scheduler started with jobs: %s",
            [job.id for job in scheduler.get_jobs()],
        )
    else:
        logger.warning("SCHEDULER_ENABLED=false: nessuna raccolta, solo dashboard e API")
    try:
        yield
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")


app = FastAPI(title="Reseller SaaS Backend", version="0.1.0", lifespan=lifespan)


@app.middleware("http")
async def forward_automations(request: Request, call_next):
    """Con raccolta e API separate (compose: ``collector`` + ``backend``) lo
    scheduler gira nel raccoglitore: i comandi della pagina Automations si
    inoltrano lì. Registrato PRIMA del CORS, che così resta il più esterno."""
    # /health/scraper: il ritmo e i blocchi del pacer vivono nel processo che raccoglie.
    forwarded = request.url.path.startswith("/api/automations") or request.url.path == "/health/scraper"
    if forwarded and settings.collector_url:
        scheduler = getattr(app.state, "scheduler", None)
        if scheduler is None or not scheduler.running:
            url = settings.collector_url.rstrip("/") + request.url.path
            if request.url.query:
                url += "?" + request.url.query
            try:
                async with httpx.AsyncClient(timeout=20, trust_env=False) as client:
                    r = await client.request(
                        request.method, url, content=await request.body(),
                        headers={"content-type": request.headers.get("content-type", "application/json")},
                    )
            except httpx.HTTPError:
                return JSONResponse({"detail": "Raccoglitore non raggiungibile"}, status_code=503)
            return Response(r.content, status_code=r.status_code,
                            media_type=r.headers.get("content-type"))
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(health_router)
app.include_router(scrape_router)
app.include_router(data_router)
app.include_router(deals_router)
app.include_router(automations_router)
app.include_router(settings_router)

# Serve le immagini scaricate dallo Sniper (sostituisce lo Storage di Supabase).
_media_dir = Path(settings.media_root)
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "reseller-backend"}
