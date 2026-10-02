"""Imparare dalle proprie riparazioni (E3 della release).

Le riparazioni registrate in pipeline (``deals.repair``) contro la stima
fotografata all'aggancio (``deals.estimate``) correggono:

- il **costo dei ricambi**: per (parte, fonte) il rapporto mediano
  reale / stimato. Da ``MIN_SAMPLES`` riparazioni in su ``parts.part_quote``
  lo applica al listino (es. gli schermi aftermarket ti costano il 15% in più
  del catalogo, per spedizioni o pezzi difettosi da ricomprare);
- il **tasso di riuscita per guasto**: quante riparazioni di telefoni con quel
  guasto (soprattutto quelli "a rischio": non si accende, scheda madre,
  acqua) sono riuscite davvero. Si mostra accanto alla stima: è il numero che
  dice quanto fidarsi di un "non si accende".

Funzioni pure (``compute_feedback``) + caricamento dal DB (``refresh``),
richiamato all'avvio, quando registri una riparazione e ogni notte.
"""

from __future__ import annotations

import logging
from statistics import median
from typing import Any

logger = logging.getLogger(__name__)

# Sotto queste riparazioni il dato è aneddoto: si mostra, non si applica.
MIN_SAMPLES = 3
# Una correzione fuori da questo intervallo è più probabilmente un errore di
# inserimento (es. 400 invece di 40) che un listino sbagliato.
RATIO_BOUNDS = (0.5, 2.0)
OUTCOMES = ("riuscita", "parziale", "fallita")

# Ultimo calcolo (lo leggono parts.part_quote e le API).
STATE: dict[str, Any] = {"parts": {}, "guasti": {}, "repairs": 0}


def _est_part_cost(item: dict[str, Any]) -> float | None:
    """Costo del SOLO ricambio nella stima (senza manodopera, se registrata)."""
    for key in ("partCost", "cost"):
        try:
            value = float(item.get(key))
        except (TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


def compute_feedback(
    deals: list[dict[str, Any]], guasti_by_listing: dict[str, list[str]] | None = None
) -> dict[str, Any]:
    """``deals``: righe con ``estimate``, ``repair``, ``listing_id``.
    ``guasti_by_listing``: listing_id → guasti (tassonomia) dell'annuncio."""
    guasti_by_listing = guasti_by_listing or {}
    ratios: dict[tuple[str, str], list[float]] = {}
    outcomes: dict[str, dict[str, int]] = {}
    repairs = 0

    for deal in deals:
        repair = deal.get("repair") or {}
        outcome = repair.get("outcome")
        if outcome not in OUTCOMES:
            continue
        repairs += 1
        est_items = (deal.get("estimate") or {}).get("repairItems") or []
        est_by_part = {i.get("part"): i for i in est_items if i.get("part")}
        for part in repair.get("parts") or []:
            est = est_by_part.get(part.get("part"))
            try:
                actual = float(part.get("cost"))
            except (TypeError, ValueError):
                continue
            est_cost = _est_part_cost(est) if est else None
            if not est_cost or actual <= 0:
                continue
            source = part.get("source") or est.get("source") or "aftermarket"
            ratio = actual / est_cost
            if RATIO_BOUNDS[0] <= ratio <= RATIO_BOUNDS[1]:
                ratios.setdefault((part["part"], source), []).append(ratio)

        for guasto in guasti_by_listing.get(str(deal.get("listing_id")), []) or ["sconosciuto"]:
            counts = outcomes.setdefault(guasto, {o: 0 for o in OUTCOMES})
            counts[outcome] += 1

    parts = {
        f"{part}:{source}": {
            "part": part, "source": source, "n": len(values),
            "ratio": round(median(values), 3),
            "applied": len(values) >= MIN_SAMPLES,
        }
        for (part, source), values in ratios.items()
    }
    guasti = {}
    for guasto, counts in outcomes.items():
        n = sum(counts.values())
        guasti[guasto] = {
            **counts, "n": n,
            # "parziale" = funziona ma con un difetto residuo: non è riuscita.
            "successPct": round(counts["riuscita"] / n * 100, 1) if n else None,
            "reliable": n >= MIN_SAMPLES,
        }
    return {"parts": parts, "guasti": guasti, "repairs": repairs}


def part_correction(part: str, source: str | None) -> dict[str, Any] | None:
    """Correzione da applicare al listino di (parte, fonte), o None."""
    entry = STATE["parts"].get(f"{part}:{source}")
    return entry if entry and entry["applied"] else None


def guasto_success(guasti: list[str]) -> dict[str, Any] | None:
    """Il tasso di riuscita più prudente fra i guasti dell'annuncio (solo
    quelli con abbastanza riparazioni), o None."""
    best = None
    for g in guasti:
        entry = STATE["guasti"].get(g)
        if entry and entry["reliable"] and (best is None or entry["successPct"] < best["successPct"]):
            best = {"guasto": g, **entry}
    return best


def refresh() -> dict[str, Any]:
    """Ricalcola dal DB e aggiorna ``STATE``. Mai bloccante: in errore lascia
    lo stato precedente."""
    from backend.core.database import _get_pool  # noqa: PLC0415
    from backend.services.defects import from_nlp  # noqa: PLC0415

    try:
        with _get_pool().connection() as conn:
            deals = conn.execute(
                "select d.listing_id, d.estimate, d.repair, t.defects_noted "
                "from public.deals d "
                "left join public.live_opportunities_tech t on t.id = d.listing_id "
                "where d.repair is not null"
            ).fetchall()
    except Exception:
        logger.exception("Feedback riparazioni: lettura fallita")
        return STATE
    guasti = {
        str(d["listing_id"]): from_nlp(d.get("defects_noted") or [], [])["guasti"]
        for d in deals if d.get("listing_id")
    }
    STATE.update(compute_feedback(deals, guasti))
    logger.info("Feedback riparazioni: %d riparazioni, %d correzioni ricambi attive",
                STATE["repairs"], sum(1 for p in STATE["parts"].values() if p["applied"]))
    return STATE
