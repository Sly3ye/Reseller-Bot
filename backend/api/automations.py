"""Controllo dei job schedulati (Cecchini, Motore Notturno, GC, AI enrich).

Espone lo scheduler APScheduler (montato su ``app.state.scheduler``) alla
dashboard: stato/prossima esecuzione, avvio immediato ("Force Run"), pausa/
ripresa e cambio cadenza per i job a intervallo. Sostituisce i controlli finti
del pannello Automations con azioni reali sul motore.
"""

from datetime import datetime

from apscheduler.triggers.interval import IntervalTrigger
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/automations", tags=["automations"])


def _scheduler(request: Request):
    scheduler = getattr(request.app.state, "scheduler", None)
    if scheduler is None:
        raise HTTPException(status_code=503, detail="Scheduler non attivo")
    return scheduler


def _job_view(job) -> dict:
    """Serializza un job per la UI (tipo trigger, cadenza, prossima run, pausa)."""
    trigger = job.trigger
    interval_minutes = None
    kind = "cron"
    if isinstance(trigger, IntervalTrigger):
        kind = "interval"
        interval_minutes = int(trigger.interval.total_seconds() // 60)
    return {
        "id": job.id,
        "name": job.name,
        "kind": kind,
        "intervalMinutes": interval_minutes,
        "trigger": str(trigger),
        "nextRun": job.next_run_time.isoformat() if job.next_run_time else None,
        # APScheduler mette next_run_time=None quando un job è in pausa.
        "paused": job.next_run_time is None,
        "category": (job.kwargs or {}).get("category"),
    }


def _get_job_or_404(request: Request, job_id: str):
    job = _scheduler(request).get_job(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' inesistente")
    return job


@router.get("")
async def list_automations(request: Request) -> dict:
    """Elenco dei job con stato e prossima esecuzione."""
    scheduler = _scheduler(request)
    jobs = [_job_view(job) for job in scheduler.get_jobs()]
    jobs.sort(key=lambda j: (j["nextRun"] is None, j["nextRun"] or ""))
    return {"running": scheduler.running, "jobs": jobs}


@router.post("/{job_id}/run")
async def run_now(request: Request, job_id: str) -> dict:
    """Forza l'esecuzione ASAP anticipando la prossima run (non blocca l'API).

    Il job parte al prossimo tick dell'event loop; se era in pausa, riprende.
    """
    scheduler = _scheduler(request)
    job = _get_job_or_404(request, job_id)
    job.modify(next_run_time=datetime.now(scheduler.timezone))
    return {"ok": True, "job": _job_view(scheduler.get_job(job_id))}


@router.post("/{job_id}/pause")
async def pause(request: Request, job_id: str) -> dict:
    """Sospende un job (resta configurato, non viene eseguito finché ripreso)."""
    scheduler = _scheduler(request)
    _get_job_or_404(request, job_id)
    scheduler.pause_job(job_id)
    return {"ok": True, "job": _job_view(scheduler.get_job(job_id))}


@router.post("/{job_id}/resume")
async def resume(request: Request, job_id: str) -> dict:
    """Riprende un job messo in pausa."""
    scheduler = _scheduler(request)
    _get_job_or_404(request, job_id)
    scheduler.resume_job(job_id)
    return {"ok": True, "job": _job_view(scheduler.get_job(job_id))}


class RescheduleBody(BaseModel):
    minutes: int = Field(ge=1, le=1440)


@router.patch("/{job_id}")
async def reschedule(request: Request, job_id: str, body: RescheduleBody) -> dict:
    """Cambia la cadenza di un job a intervallo (minuti)."""
    scheduler = _scheduler(request)
    job = _get_job_or_404(request, job_id)
    if not isinstance(job.trigger, IntervalTrigger):
        raise HTTPException(
            status_code=400,
            detail="La cadenza si può cambiare solo per i job a intervallo",
        )
    scheduler.reschedule_job(
        job_id,
        trigger=IntervalTrigger(minutes=body.minutes, timezone=scheduler.timezone),
    )
    return {"ok": True, "job": _job_view(scheduler.get_job(job_id))}
