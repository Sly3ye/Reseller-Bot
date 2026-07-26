import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from backend.api.automations import router as automations_router
from backend.api.data import router as data_router
from backend.api.deals import router as deals_router
from backend.api.health import router as health_router
from backend.api.scrape import router as scrape_router
from backend.core.config import settings
from backend.core.scheduler import create_scheduler

logger = logging.getLogger(__name__)

# Comma-separated list of allowed frontend origins (Next.js dev server default).
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000"
    ).split(",")
    if origin.strip()
]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background scheduler with the app and stop it on shutdown."""
    scheduler = create_scheduler()
    scheduler.start()
    app.state.scheduler = scheduler
    logger.info(
        "Scheduler started with jobs: %s",
        [job.id for job in scheduler.get_jobs()],
    )
    try:
        yield
    finally:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler stopped")


app = FastAPI(title="Reseller SaaS Backend", version="0.1.0", lifespan=lifespan)

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

# Serve le immagini scaricate dallo Sniper (sostituisce lo Storage di Supabase).
_media_dir = Path(settings.media_root)
_media_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media", StaticFiles(directory=str(_media_dir)), name="media")


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "reseller-backend"}
