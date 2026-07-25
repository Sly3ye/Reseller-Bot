import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.core.config import settings
from backend.services.ai_analysis import enrich_missing
from backend.services.garbage_collector import run_garbage_collector
from backend.tasks import run_nightly_batch_all_products, run_sniper_all_products

logger = logging.getLogger(__name__)

# Local timezone so "03:00" means 3 AM in Italy, not UTC.
SCHEDULER_TIMEZONE = "Europe/Rome"


def create_scheduler() -> AsyncIOScheduler:
    """Build the background scheduler with the scraping engines.

    - Motore Notturno: recomputes market trends daily at 03:00.
    - Garbage Collector: verifica annunci rimossi ogni notte alle 04:30
      (alimenta il time-to-sale oltre a pulire il feed).
    - Cecchino Tech: smartphone sniper every 5 minutes — su Subito il primo
      che scrive vince, e una pagina API tech costa pochissimo proxy.
    - Cecchino Auto: dedicated automobile sniper every 15 minutes.

    I due Cecchini sono scoping-disgiunti per categoria (tech vs automobile),
    così non si scansionano gli stessi target due volte. La cadenza auto resta
    a 15' per evitare l'accavallamento: con molti target auto + download
    immagini un giro può superare i 5 minuti.

    All jobs are async httpx-based, so they never block the FastAPI event loop.
    """
    scheduler = AsyncIOScheduler(
        timezone=SCHEDULER_TIMEZONE,
        job_defaults={
            "coalesce": True,       # collapse missed runs into one
            "max_instances": 1,     # never overlap a job with itself
            "misfire_grace_time": 300,
        },
    )

    scheduler.add_job(
        run_nightly_batch_all_products,
        trigger=CronTrigger(hour=3, minute=0),
        id="nightly_batch",
        name="Motore Notturno (market trends)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_garbage_collector,
        trigger=CronTrigger(hour=4, minute=30),
        id="garbage_collector",
        name="Garbage Collector (annunci rimossi → time-to-sale)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_sniper_all_products,
        trigger=IntervalTrigger(minutes=5),
        kwargs={"category": "smartphone"},
        id="sniper_live",
        name="Cecchino Tech (smartphone, 5 min)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_sniper_all_products,
        trigger=IntervalTrigger(minutes=15),
        kwargs={"category": "automobile", "pages": 1},
        id="sniper_auto_live",
        name="Cecchino Auto (automobile, 15 min)",
        replace_existing=True,
    )

    # AI locale: consuma il backlog delle descrizioni un po' alla volta (solo se
    # abilitata). Batch piccolo per non saturare l'LLM locale.
    if settings.ai_enabled:
        scheduler.add_job(
            enrich_missing,
            trigger=IntervalTrigger(minutes=10),
            kwargs={"limit": 30, "category": "smartphone"},
            id="ai_enrich",
            name="AI enrich descrizioni (smartphone, 10 min)",
            replace_existing=True,
        )

    return scheduler
