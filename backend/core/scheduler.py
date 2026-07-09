import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.tasks import run_nightly_batch_all_products, run_sniper_all_products

logger = logging.getLogger(__name__)

# Local timezone so "03:00" means 3 AM in Italy, not UTC.
SCHEDULER_TIMEZONE = "Europe/Rome"


def create_scheduler() -> AsyncIOScheduler:
    """Build the background scheduler with the scraping engines.

    - Motore Notturno: recomputes market trends daily at 03:00.
    - Cecchino Live: hunts fresh opportunities every 15 minutes (all verticals).
    - Cecchino Auto: dedicated automobile sniper every 5 minutes, 2 API blocks
      per run (the native JSON API is fast enough for a tight interval).

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
        run_sniper_all_products,
        trigger=IntervalTrigger(minutes=15),
        id="sniper_live",
        name="Cecchino Live (opportunita)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_sniper_all_products,
        trigger=IntervalTrigger(minutes=5),
        kwargs={"category": "automobile", "pages": 2},
        id="sniper_auto_live",
        name="Cecchino Auto (automobile, 5 min)",
        replace_existing=True,
    )

    return scheduler
