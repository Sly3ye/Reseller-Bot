import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.api.health import router as health_router
from backend.api.scrape import router as scrape_router
from backend.core.scheduler import create_scheduler

logger = logging.getLogger(__name__)


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

app.include_router(health_router)
app.include_router(scrape_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"status": "ok", "service": "reseller-backend"}
