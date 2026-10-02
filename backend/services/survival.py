"""Tempo di vendita onesto: stima di sopravvivenza (Kaplan–Meier) + natura
della sparizione di un annuncio. Modulo puro (zero DB) → testabile.

Il problema. "Giorni medi di vendita" calcolati SOLO sugli annunci spariti
sono ottimisti: chi resta online 3 mesi non è ancora sparito e quindi non
conta, mentre i venduti in 2 giorni contano subito. E non ogni sparizione è
una vendita: un annuncio può scadere (Subito lo toglie dopo un anno) o essere
ritirato da chi rinuncia.

La soluzione statistica classica è Kaplan–Meier: ogni annuncio contribuisce
con quanti giorni è rimasto online; i venduti sono "eventi", gli annunci
ancora attivi (e quelli spariti senza vendita) sono "censurati", cioè
sappiamo solo che fino a quel giorno NON si erano venduti. Ne esce la curva
"probabilità di essere ancora invenduto dopo t giorni", da cui la mediana
(il giorno in cui metà degli annunci è venduta) e la probabilità di vendere
entro 7/30 giorni.
"""

from __future__ import annotations

from typing import Iterable

# Si pensava che Subito togliesse gli annunci dopo un anno: falso. Il
# 2026-10-02 c'erano 1.528 iPhone di privati online da 12–21 mesi. Una
# sparizione si dà per "scaduta" solo oltre i due anni; sotto decidono le
# regole sul ritirato (età, nessun ribasso, prezzo sopra mercato).
EXPIRY_DAYS = 730
# Ritirato probabile: online a lungo, mai ribassato, ancora sopra mercato.
WITHDRAW_MIN_DAYS = 90
WITHDRAW_OVER_MARKET = 1.10


def removal_kind(
    age_days: float,
    had_drop: bool,
    price: float | None,
    market_median: float | None,
) -> str:
    """Natura probabile di una sparizione: "venduto", "scaduto" o "ritirato".

    È un'euristica dichiarata (Subito non dice perché un annuncio sparisce):
    - oltre 2 anni di età → scaduto;
    - online da ≥90 giorni, mai ribassato e ancora ≥10% sopra la mediana del
      mercato → ritirato (chi vende davvero di solito ribassa prima);
    - altrimenti → venduto.
    """
    if age_days >= EXPIRY_DAYS:
        return "scaduto"
    if (
        age_days >= WITHDRAW_MIN_DAYS
        and not had_drop
        and price is not None
        and market_median
        and price >= market_median * WITHDRAW_OVER_MARKET
    ):
        return "ritirato"
    return "venduto"


def kaplan_meier(observations: Iterable[tuple[float, ...]]) -> list[tuple[float, float]]:
    """Curva di sopravvivenza: [(giorno, S)] con S = quota ancora invenduta.

    ``observations``: (giorni online, venduto?) oppure (giorni online,
    venduto?, giorno di entrata). Censurati = venduto False.

    **Entrata ritardata** (troncamento a sinistra): un annuncio pubblicato 40
    giorni prima che lo vedessimo entra nell'insieme a rischio solo dal giorno
    40. Senza, lo stock trovato già vecchio (backfill, inventario) conterebbe
    solo i "sopravvissuti" e allungherebbe i tempi di vendita per mesi.
    Insieme a rischio al giorno t: entrata ≤ t ≤ uscita. A parità di giorno
    gli eventi si contano prima dei censurati (convenzione standard)."""
    from bisect import bisect_left, bisect_right  # noqa: PLC0415

    obs = [(float(o[0]), bool(o[1]), float(o[2]) if len(o) > 2 else 0.0) for o in observations]
    obs = [(t, ev, min(max(0.0, entry), t)) for t, ev, entry in obs]
    entries = sorted(entry for _, _, entry in obs)
    exits = sorted(t for t, _, _ in obs)
    events_at: dict[float, int] = {}
    for t, ev, _ in obs:
        if ev:
            events_at[t] = events_at.get(t, 0) + 1
    survival = 1.0
    curve: list[tuple[float, float]] = []
    for t in sorted(events_at):
        at_risk = bisect_right(entries, t) - bisect_left(exits, t)
        if at_risk <= 0:
            continue
        survival *= 1 - min(events_at[t], at_risk) / at_risk
        curve.append((t, survival))
    return curve


def km_median(curve: list[tuple[float, float]]) -> float | None:
    """Primo giorno in cui la quota invenduta scende a ≤ 50% (None se mai:
    con i dati attuali meno di metà degli annunci risulta venduta)."""
    for t, s in curve:
        if s <= 0.5:
            return t
    return None


def km_sold_by(curve: list[tuple[float, float]], day: float) -> float:
    """Probabilità di essere venduto entro ``day`` giorni (1 − S(day))."""
    survival = 1.0
    for t, s in curve:
        if t > day:
            break
        survival = s
    return 1 - survival


def survival_summary(observations: list[tuple[float, ...]]) -> dict[str, float | int | None]:
    """Sintesi per la UI. ``medianDays`` None = metà degli annunci non si è
    ancora venduta nella finestra osservata (dato onesto, non un buco)."""
    curve = kaplan_meier(observations)
    events = sum(1 for o in observations if o[1])
    return {
        "medianDays": round(km_median(curve), 1) if km_median(curve) is not None else None,
        "sold7dPct": round(km_sold_by(curve, 7) * 100, 1),
        "sold30dPct": round(km_sold_by(curve, 30) * 100, 1),
        "events": events,
        "censored": len(observations) - events,
    }
