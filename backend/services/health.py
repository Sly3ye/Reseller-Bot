"""Salute dello scraper (Fase 3): rileva quando la raccolta si blocca.

Il rischio operativo n.1 di un bot 24/7: smettere di raccogliere in SILENZIO
(Akamai che ri-blocca, proxy morto, Subito che cambia). Qui ogni giro dello
Sniper registra il suo esito in ``scrape_runs``; se un giro passa a "down"
(tutti i target falliti o zero annunci) si manda un alert Telegram, e uno di
ripristino quando torna a funzionare — così te ne accorgi subito.

``compute_status`` è puro → testabile senza DB.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_status(targets: int, ok: int, failed: int, scraped: int) -> str:
    """Stato di un giro: ok / degraded / down / idle.

    - idle: nessun target attivo.
    - down: tutti i target hanno fallito (blocco/proxy), oppure nessun annuncio
      raccolto pur avendo target (probabile soft-block).
    - degraded: qualche target fallito ma non tutti.
    - ok: tutti i target ok e almeno un annuncio raccolto.
    """
    if targets <= 0:
        return "idle"
    if ok == 0 or scraped == 0:
        return "down"
    if failed > 0:
        return "degraded"
    return "ok"


def record_run(
    category: str,
    targets: int,
    ok: int,
    failed: int,
    scraped: int,
    new_count: int,
    requests: int | None = None,
    gaps: int | None = None,
) -> dict[str, Any]:
    """Registra l'esito del giro e rileva le transizioni down/ripristino.

    ``requests`` = chiamate hades del giro (il costo, da un IP solo);
    ``gaps`` = target che non si sono ricongiunti con la scansione precedente
    (annunci persi → cadenza troppo lenta per quella categoria).

    Ritorna {status, previous, went_down, recovered}. Import DB lazy per non
    accoppiare il modulo (compute_status resta puro).
    """
    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)

    status = compute_status(targets, ok, failed, scraped)
    previous: str | None = None
    db = get_db()
    try:
        last = (
            db.table("scrape_runs")
            .select("status")
            .eq("category", category)
            .order("ran_at", desc=True)
            .limit(1)
            .execute()
            .data
        )
        previous = last[0]["status"] if last else None
        row = {
            "category": category,
            "status": status,
            "targets": targets,
            "ok": ok,
            "failed": failed,
            "scraped": scraped,
            "new_count": new_count,
        }
        try:
            db.table("scrape_runs").insert(
                {**row, "requests": requests, "gaps": gaps}
            ).execute()
        except Exception:
            # Migrazione 18 non ancora applicata: si registra senza le colonne nuove.
            db.table("scrape_runs").insert(row).execute()
    except Exception:
        logger.warning("scrape_runs non disponibile: monitoraggio salute limitato.")

    return {
        "status": status,
        "previous": previous,
        # Alert solo sulla TRANSIZIONE (evita spam a ogni giro).
        "went_down": status == "down" and previous not in (None, "down"),
        "recovered": status in ("ok", "degraded") and previous == "down",
    }


def _coverage(db: Any, cat: str, recent: list[dict[str, Any]]) -> dict[str, Any]:
    """Copertura per categoria: target attivi, annunci in magazzino, immessi/24h."""
    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    table = "live_opportunities_auto" if cat == "automobile" else "live_opportunities_tech"
    active_targets = active_listings = None
    try:
        active_targets = (
            db.table("target_models").select("id", count="exact")
            .eq("is_active", True).eq("category", cat).limit(1).execute().count
        )
    except Exception:
        pass
    try:
        active_listings = (
            db.table(table).select("id", count="exact")
            .in_("status", ["nuovo", "visto"]).limit(1).execute().count
        )
    except Exception:
        pass

    # Annunci nuovi nelle ultime 24h = somma dei new_count dei giri recenti.
    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    new_24h = 0
    for r in recent:
        ts = None
        try:
            ts = datetime.fromisoformat(str(r.get("ran_at")).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        if ts and ts >= cutoff:
            new_24h += r.get("new_count") or 0

    return {
        "activeTargets": active_targets,
        "activeListings": active_listings,
        "new24h": new_24h,
        "targets": _coverage_by_target(db, cat, table),
    }


def _coverage_by_target(db: Any, cat: str, table: str) -> list[dict[str, Any]]:
    """Copertura per singolo target: quanti annunci abbiamo VISTO in totale,
    quanti sono ancora attivi e quanti sono già spariti (venduti/ritirati).

    "Attivi" è una fotografia del momento e oscilla (ne entrano di nuovi, altri
    spariscono); "totale visti" è cumulativo e dice davvero quanto mercato
    abbiamo osservato per quel modello — il numero che conta per fidarsi delle
    statistiche di quella variante.
    """
    try:
        targets = (
            db.table("target_models")
            .select("id, query")
            .eq("is_active", True)
            .eq("category", cat)
            .execute()
            .data
            or []
        )
        rows = (
            db.table(table)
            .select("target_id, status, found_at")
            .limit(40000)
            .execute()
            .data
            or []
        )
    except Exception:
        return []

    from datetime import datetime, timedelta, timezone  # noqa: PLC0415

    cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
    names = {t["id"]: t["query"] for t in targets}
    stats: dict[str, dict[str, int]] = {
        t["query"]: {"active": 0, "sold": 0, "total": 0, "new24h": 0} for t in targets
    }
    for row in rows:
        name = names.get(row.get("target_id"))
        if name is None:
            continue
        entry = stats[name]
        entry["total"] += 1
        status = row.get("status")
        if status in ("nuovo", "visto"):
            entry["active"] += 1
        elif status == "venduto_rimosso":
            entry["sold"] += 1
        try:
            found = datetime.fromisoformat(str(row.get("found_at")).replace("Z", "+00:00"))
            if found >= cutoff:
                entry["new24h"] += 1
        except (ValueError, TypeError):
            pass

    return sorted(
        ({"query": q, **s} for q, s in stats.items()),
        key=lambda x: -x["total"],
    )


def get_health() -> dict[str, Any]:
    """Snapshot per /health/scraper: ultimo giro, storico recente, copertura, config."""
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.core.config import settings  # noqa: PLC0415
    from backend.scrapers.subito import pacer  # noqa: PLC0415

    out: dict[str, Any] = {
        "proxy_configured": bool(settings.proxy_url),
        "pacing": pacer.snapshot(),
        "impersonate_pool": settings.impersonate_pool,
        "scraper": {},
        "recent": {},
        "coverage": {},
    }
    db = get_db()
    for cat in ("smartphone", "automobile"):
        recent: list[dict[str, Any]] = []
        try:
            recent = (
                db.table("scrape_runs")
                # "*": include requests/gaps se la migrazione 18 è applicata.
                .select("*")
                .eq("category", cat)
                .order("ran_at", desc=True)
                .limit(20)
                .execute()
                .data
                or []
            )
        except Exception:
            recent = []
        out["scraper"][cat] = recent[0] if recent else None
        out["recent"][cat] = recent
        out["coverage"][cat] = _coverage(db, cat, recent)
    return out
