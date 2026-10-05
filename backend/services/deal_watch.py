"""Emivita degli affari (Goal Version §1.3): quanto resta online un'occasione
dopo l'alert.

Ogni affare segnalato (``new_deal``, ``repair_deal``; registrato anche senza
Telegram, vedi ``notifications.notify_deals``) si ricontrolla a intervalli
crescenti: dopo 10 minuti, poi quando è passata metà della sua età (10', 15',
22', 34'... circa 10 controlli in 7 giorni), finché la pagina sparisce. Lì si
segna ``gone_at``: l'affare è sparito fra ``last_checked_at`` e ``gone_at``.

Ne esce la metrica che dice quanto in fretta bisogna muoversi ("metà degli
affari iPhone sparisce entro 2 ore") e la base del profitto atteso per ora
(P2). Ogni controllo è una pagina dallo stesso IP, dal pacer globale (job
``ricontrollo_affari``): con qualche decina di affari al giorno sono poche
centinaia di richieste.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

WATCH_TYPES = ("new_deal", "repair_deal")
WATCH_DAYS = 7
BATCH = 20
TABLES = {"smartphone": "live_opportunities_tech", "automobile": "live_opportunities_auto"}
ACTIVE = ("nuovo", "visto")
# Orizzonti della metrica (minuti): quota sparita entro ciascuno.
HORIZONS_MIN = (15, 30, 60, 120, 360, 1440, 4320, 10080)
# Sotto questo numero di affari maturi la quota a un orizzonte non si mostra.
MIN_SAMPLE = 5


def _due(limit: int) -> list[dict[str, Any]]:
    """Affari da ricontrollare adesso (i più in ritardo per primi)."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column("sent_alerts", "gone_at"):
        return []
    with _get_pool().connection() as conn:
        rows = conn.execute(
            """
            select s.id::text as alert_id, s.listing_id::text as listing_id,
                   coalesce(s.category, 'smartphone') as category,
                   coalesce(t.listing_url, a.listing_url) as listing_url,
                   coalesce(t.status::text, a.status::text) as status
            from public.sent_alerts s
            left join public.live_opportunities_tech t on t.id = s.listing_id
            left join public.live_opportunities_auto a on a.id = s.listing_id
            where s.alert_type = any(%s) and s.gone_at is null
              and s.sent_at > now() - make_interval(days => %s)
              and now() - coalesce(s.last_checked_at, s.sent_at)
                  >= greatest(interval '10 minutes', (now() - s.sent_at) / 2)
            -- Prima gli iPhone (il business principale), poi i più in ritardo.
            order by (coalesce(s.category, 'smartphone') <> 'smartphone'), coalesce(s.last_checked_at, s.sent_at)
            limit %s
            """,
            (list(WATCH_TYPES), WATCH_DAYS, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def _record(gone: list[str], checked: list[str], removed: dict[str, list[str]]) -> None:
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        if gone:
            # last_checked_at resta l'ultimo controllo in cui era online.
            conn.execute("update public.sent_alerts set gone_at = now() where id = any(%s::uuid[])", (gone,))
        if checked:
            conn.execute("update public.sent_alerts set last_checked_at = now() where id = any(%s::uuid[])",
                         (checked,))
        # Pagina sparita = annuncio rimosso, come fa il GC (stesso stato).
        for category, ids in removed.items():
            conn.execute(
                f"update public.{TABLES[category]} set status = 'venduto_rimosso', updated_at = now() "
                "where id = any(%s::uuid[]) and status in ('nuovo', 'visto')",
                (ids,),
            )


async def watch_deals(limit: int = BATCH) -> dict[str, int]:
    """Un giro di ricontrollo (schedulato ogni 10 minuti)."""
    from backend.services.garbage_collector import check_pages  # noqa: PLC0415

    rows = await asyncio.to_thread(_due, limit)
    if not rows:
        return {"checked": 0, "gone": 0}
    gone: list[str] = []
    checked: list[str] = []
    to_fetch: list[dict[str, Any]] = []
    for row in rows:
        if row["status"] is None:
            checked.append(row["alert_id"])          # riga non più nel DB (fusa): niente da vedere
        elif row["status"] not in ACTIVE:
            gone.append(row["alert_id"])             # già marcato rimosso da inventario o GC
        else:
            to_fetch.append({"id": row["listing_id"], "listing_url": row["listing_url"], "row": row})
    removed: dict[str, list[str]] = {}
    if to_fetch:
        results, state = await check_pages(to_fetch, job="ricontrollo_affari")
        for item in to_fetch:
            outcome = results.get(item["id"])
            if outcome is None:
                continue                              # bloccato o non verificato: al prossimo giro
            if outcome:
                gone.append(item["row"]["alert_id"])
                removed.setdefault(item["row"]["category"], []).append(item["id"])
            else:
                checked.append(item["row"]["alert_id"])
        if state.get("aborted"):
            logger.warning("Ricontrollo affari fermato dai blocchi dopo %d pagine", state.get("checked", 0))
    await asyncio.to_thread(_record, gone, checked, removed)
    if gone:
        logger.info("Ricontrollo affari: %d spariti su %d controllati", len(gone), len(gone) + len(checked))
    return {"checked": len(gone) + len(checked), "gone": len(gone)}


# -------------------------------------------------------------------- metrica

def half_life_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Da righe {ageMin, goneMin|None} → quota sparita entro ogni orizzonte ed
    emivita (primo orizzonte con almeno metà sparita).

    Per ogni orizzonte contano solo gli affari più vecchi dell'orizzonte
    stesso (gli altri non hanno ancora avuto il tempo di sparire): niente
    distorsione verso il basso per gli affari di stamattina.
    """
    within: dict[str, float | None] = {}
    half_life: int | None = None
    for h in HORIZONS_MIN:
        mature = [r for r in rows if r["ageMin"] >= h]
        if len(mature) < MIN_SAMPLE:
            within[str(h)] = None
            continue
        share = sum(1 for r in mature if r["goneMin"] is not None and r["goneMin"] <= h) / len(mature)
        within[str(h)] = round(share, 3)
        if half_life is None and share >= 0.5:
            half_life = h
    return {
        "n": len(rows),
        "gone": sum(1 for r in rows if r["goneMin"] is not None),
        "withinPct": within,
        "halfLifeMin": half_life,
    }


def deal_half_life(category: str) -> dict[str, Any] | None:
    """Emivita degli affari segnalati negli ultimi 14 giorni per la categoria."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column("sent_alerts", "gone_at"):
        return None
    with _get_pool().connection() as conn:
        rows = conn.execute(
            """
            select extract(epoch from now() - sent_at) / 60 as age_min,
                   extract(epoch from gone_at - sent_at) / 60 as gone_min
            from public.sent_alerts
            where alert_type = any(%s) and coalesce(category, 'smartphone') = %s
              and sent_at > now() - interval '14 days'
            """,
            (list(WATCH_TYPES), category),
        ).fetchall()
    return half_life_stats([{"ageMin": float(r["age_min"]),
                             "goneMin": float(r["gone_min"]) if r["gone_min"] is not None else None}
                            for r in rows])
