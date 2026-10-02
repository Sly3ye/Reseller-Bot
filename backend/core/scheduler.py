import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.core.config import settings
from backend.services.ai_analysis import enrich_missing
from backend.services.garbage_collector import run_garbage_collector
from backend.services.sweep import reconcile_inventory, run_sweep
from backend.tasks import run_nightly_batch_all_products, run_sniper_all_products

logger = logging.getLogger(__name__)

# Local timezone so "03:00" means 3 AM in Italy, not UTC.
SCHEDULER_TIMEZONE = "Europe/Rome"


def create_scheduler() -> AsyncIOScheduler:
    """Build the background scheduler with the scraping engines.

    - Motore Notturno: recomputes market trends daily at 03:00.
    - Garbage Collector: verifica annunci rimossi ogni notte alle 04:30
      (alimenta il time-to-sale oltre a pulire il feed).
    - Cecchino Tech / Auto: ogni SNIPER_TECH/AUTO_INTERVAL_MIN (default 15/30).
      Da un solo IP ogni richiesta conta: ogni target pagina all'indietro solo
      fino alla scansione precedente, quindi una cadenza più lenta non perde
      annunci (lo misura scrape_runs.gaps), costa solo freschezza degli alert.

    I due Cecchini sono scoping-disgiunti per categoria (tech vs automobile),
    così non si scansionano gli stessi target due volte; il ritmo delle
    richieste lo regola il pacer globale dello scraper.

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

    # Tech: inventario completo + verifica dei soli spariti (~600 richieste
    # invece di una per annuncio attivo). Prima del Motore Notturno delle 03:00,
    # che calcola le medie tech dal DB appena riconciliato.
    scheduler.add_job(
        reconcile_inventory,
        trigger=CronTrigger(hour=1, minute=30),
        kwargs={"category": "smartphone"},
        id="inventory_tech",
        name="Inventario Tech (stock completo, prezzi, rimossi → time-to-sale)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_garbage_collector,
        trigger=CronTrigger(hour=4, minute=30),
        kwargs={"category": "automobile"},
        id="garbage_collector",
        name="Garbage Collector Auto (annunci rimossi → time-to-sale)",
        replace_existing=True,
    )

    # Tech: UNA ricerca ampia "iphone" invece di una per target (vedi
    # services/sweep.py). L'id resta "sniper_live" per la UI Automations.
    scheduler.add_job(
        run_sweep,
        trigger=IntervalTrigger(minutes=settings.sniper_tech_interval_min),
        kwargs={"category": "smartphone"},
        id="sniper_live",
        name=f"Cecchino Tech (ricerca ampia iPhone, {settings.sniper_tech_interval_min} min)",
        replace_existing=True,
    )

    scheduler.add_job(
        run_sniper_all_products,
        trigger=IntervalTrigger(minutes=settings.sniper_auto_interval_min),
        kwargs={"category": "automobile"},
        id="sniper_auto_live",
        name=f"Cecchino Auto (automobile, {settings.sniper_auto_interval_min} min)",
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
