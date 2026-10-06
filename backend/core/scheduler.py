import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from backend.core.config import settings
from backend.services.ai_analysis import enrich_missing
from backend.services.backup_status import check_backup
from backend.services.photo_backfill import (
    complete_car_galleries,
    fill_missing_car_photos,
    fill_missing_photos,
)
from backend.services.repair_feedback import refresh as refresh_repair_feedback
from backend.services.deal_watch import watch_deals
from backend.services.drift import drift_check
from backend.services.request_budget import flush_request_counts
from backend.services.retention import nightly_housekeeping
from backend.services.telegram_bot import poll_telegram
from backend.services.garbage_collector import run_garbage_collector
from backend.services.sweep import (
    drain_verify_queue,
    head_poll,
    inventory_watchdog,
    reconcile_auto_inventory,
    reconcile_inventory,
    run_nightly_once,
    run_sweep,
)
from backend.tasks import run_sniper_all_products

logger = logging.getLogger(__name__)

# Local timezone so "03:00" means 3 AM in Italy, not UTC. Va passato a OGNI
# CronTrigger: in APScheduler 3 un trigger senza timezone usa quello del
# container (UTC), non quello dello scheduler (bug fino al 2026-10-02: i job
# notturni giravano 2 ore dopo).
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
        run_nightly_once,
        # Di norma parte a fine inventario (services/sweep.py); qui solo il
        # ripiego se l'inventario non è partito affatto.
        trigger=CronTrigger(hour=6, minute=0, timezone=SCHEDULER_TIMEZONE),
        id="nightly_batch",
        name="Motore Notturno (market trends)",
        replace_existing=True,
    )

    # Tech: inventario completo + verifica dei soli spariti (~600 richieste
    # invece di una per annuncio attivo). Prima del Motore Notturno delle 03:00,
    # che calcola le medie tech dal DB appena riconciliato.
    scheduler.add_job(
        reconcile_inventory,
        trigger=CronTrigger(hour=1, minute=30, timezone=SCHEDULER_TIMEZONE),
        kwargs={"category": "smartphone"},
        id="inventory_tech",
        name="Inventario Tech (stock completo, prezzi, rimossi → time-to-sale)",
        replace_existing=True,
    )

    # PC spento all'1:30 → l'inventario si recupera appena possibile.
    scheduler.add_job(
        inventory_watchdog,
        trigger=IntervalTrigger(minutes=30),
        kwargs={"category": "smartphone"},
        id="inventory_watchdog",
        name="Recupero inventario (se l'ultimo ha più di 26h)",
        replace_existing=True,
    )

    if settings.auto_full_category:
        # Foto auto: la prima di ogni auto (formato galleria) e la galleria
        # completa per le occasioni (services/photo_backfill.py).
        scheduler.add_job(
            fill_missing_car_photos,
            trigger=IntervalTrigger(minutes=2),
            id="photo_backfill_auto",
            name="Foto auto (prima foto di ogni auto)",
            replace_existing=True,
        )
        scheduler.add_job(
            complete_car_galleries,
            trigger=IntervalTrigger(minutes=10),
            id="car_galleries",
            name="Foto auto (galleria completa di salvate, pipeline, affari)",
            replace_existing=True,
        )
        # Tutte le auto: inventario a rotazione (una fetta di fasce a notte)
        # al posto del Garbage Collector, che verificherebbe pagina per pagina
        # mezzo milione di annunci.
        scheduler.add_job(
            reconcile_auto_inventory,
            trigger=CronTrigger(hour=3, minute=30, timezone=SCHEDULER_TIMEZONE),
            id="inventory_auto",
            name=f"Inventario Auto (1/{settings.auto_inventory_slices} delle fasce a notte)",
            replace_existing=True,
        )
        scheduler.add_job(
            inventory_watchdog,
            trigger=IntervalTrigger(minutes=30),
            kwargs={"category": "automobile"},
            id="inventory_watchdog_auto",
            name="Recupero inventario auto (se l'ultima fetta ha più di 26h)",
            replace_existing=True,
        )

    else:
        scheduler.add_job(
            run_garbage_collector,
            trigger=CronTrigger(hour=4, minute=30, timezone=SCHEDULER_TIMEZONE),
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

    # Auto: tutta la categoria (sweep come per gli iPhone) o i soli target.
    scheduler.add_job(
        run_sweep if settings.auto_full_category else run_sniper_all_products,
        trigger=IntervalTrigger(minutes=settings.sniper_auto_interval_min),
        kwargs={"category": "automobile"},
        id="sniper_auto_live",
        name=(f"Cecchino Auto (tutte le auto, {settings.sniper_auto_interval_min} min)"
              if settings.auto_full_category
              else f"Cecchino Auto (target, {settings.sniper_auto_interval_min} min)"),
        replace_existing=True,
    )

    # Backup (F2): lo fa il servizio `backup` del compose; qui solo il
    # controllo, a metà mattina così un PC spento di notte ha tempo di farlo.
    scheduler.add_job(
        check_backup,
        trigger=CronTrigger(hour=10, minute=0, timezone=SCHEDULER_TIMEZONE),
        id="backup_check",
        name="Controllo backup (allarme se fallito o più vecchio di 36h)",
        replace_existing=True,
    )

    # Foto dell'archivio: le righe salvate senza foto (inventario, deep sweep)
    # le recuperano a lotti dalla CDN immagini, che non pesa sul budget hades.
    scheduler.add_job(
        fill_missing_photos,
        trigger=IntervalTrigger(minutes=2),
        id="photo_backfill",
        name="Foto dell'archivio (download a lotti dalla CDN)",
        replace_existing=True,
    )

    # Testa della coda: pagina 1 ogni HEAD_POLL_SECONDS → alert in secondi
    # (Goal Version §3). Auto solo con la raccolta completa.
    if settings.head_poll_seconds > 0:
        for cat in ("smartphone", "automobile") if settings.auto_full_category else ("smartphone",):
            scheduler.add_job(
                head_poll,
                trigger=IntervalTrigger(seconds=settings.head_poll_seconds),
                kwargs={"category": cat},
                id=f"head_{cat}",
                name=f"Testa della coda {cat} (pagina 1 ogni {settings.head_poll_seconds} s)",
                replace_existing=True,
            )

    # Verifiche dei venduti in coda (dall'inventario): riprese dopo riavvii,
    # macchina spenta o blocchi; il pezzo fatto resta fatto.
    scheduler.add_job(
        drain_verify_queue,
        trigger=IntervalTrigger(minutes=30),
        kwargs={"category": "smartphone"},
        id="verify_queue",
        name="Verifiche venduti in coda (riprende da dove si era fermato)",
        replace_existing=True,
    )

    # Emivita degli affari: ricontrollo degli affari segnalati finché spariscono.
    scheduler.add_job(
        watch_deals,
        trigger=IntervalTrigger(minutes=10),
        id="deal_watch",
        name="Ricontrollo affari segnalati (emivita)",
        replace_existing=True,
    )

    # Deriva del formato: campi che si svuotano negli ultimi annunci → allarme ops.
    scheduler.add_job(
        drift_check,
        trigger=IntervalTrigger(hours=1),
        id="drift_check",
        name="Allarmi di deriva dei campi (ultimi annunci vs base)",
        replace_existing=True,
    )

    # Budget di richieste per job → request_log (ogni 5 minuti).
    scheduler.add_job(
        flush_request_counts,
        trigger=IntervalTrigger(minutes=5),
        id="request_budget",
        name="Budget richieste per job (request_log)",
        replace_existing=True,
    )

    # Bottoni e risposte agli alert Telegram → pipeline (long polling 25 s).
    if settings.telegram_bot_token:
        scheduler.add_job(
            poll_telegram,
            trigger=IntervalTrigger(seconds=30),
            id="telegram_bot",
            name="Bot Telegram (azioni sugli alert → pipeline)",
            replace_existing=True,
        )

    # Pulizie della notte, dopo gli inventari: conservazione (via descrizione e
    # venditore dagli annunci spariti da RETENTION_DAYS) e ambito iPhone
    # (fuori ambito in archivio). services/retention.py, services/scope.py.
    scheduler.add_job(
        nightly_housekeeping,
        trigger=CronTrigger(hour=5, minute=15, timezone=SCHEDULER_TIMEZONE),
        id="retention",
        name="Pulizie della notte (conservazione dati, ambito iPhone)",
        replace_existing=True,
    )

    # Correzioni dalle riparazioni (E3): si ricalcolano anche a ogni riparazione
    # registrata; qui di notte, per sicurezza.
    scheduler.add_job(
        refresh_repair_feedback,
        trigger=CronTrigger(hour=2, minute=50, timezone=SCHEDULER_TIMEZONE),
        id="repair_feedback",
        name="Correzioni ricambi dalle tue riparazioni",
        replace_existing=True,
    )

    # AI locale: analizza TUTTI gli iPhone attivi (prima i candidati, poi il
    # resto, poi le analisi di una versione vecchia). Ogni giro lavora al massimo
    # AI_RUN_SECONDS con una pausa tra due annunci: il Mac non resta a pieno
    # carico e Ollama tiene il modello in memoria tra un giro e l'altro.
    if settings.ai_enabled:
        scheduler.add_job(
            enrich_missing,
            trigger=IntervalTrigger(minutes=settings.ai_interval_min),
            kwargs={"limit": 30, "category": "smartphone"},
            id="ai_enrich",
            name=f"AI analisi annunci (smartphone, {settings.ai_interval_min} min)",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )

    if settings.scheduler_only:
        keep = {j.strip() for j in settings.scheduler_only.split(",") if j.strip()}
        for job in scheduler.get_jobs():
            if job.id not in keep:
                scheduler.remove_job(job.id)
    if settings.scheduler_skip:
        skip = {j.strip() for j in settings.scheduler_skip.split(",") if j.strip()}
        for job in scheduler.get_jobs():
            if job.id in skip:
                scheduler.remove_job(job.id)
    return scheduler
