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

# Subito toglie gli annunci dopo 365 giorni: una sparizione oltre questa età
# è una scadenza, non una vendita.
EXPIRY_DAYS = 330
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
    - oltre ~11 mesi di età → scaduto (lo ha tolto Subito);
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


def kaplan_meier(observations: Iterable[tuple[float, bool]]) -> list[tuple[float, float]]:
    """Curva di sopravvivenza: [(giorno, S)] con S = quota ancora invenduta.

    ``observations``: (giorni online, venduto?). Censurati = venduto False.
    A parità di giorno gli eventi si contano prima dei censurati (convenzione
    standard)."""
    obs = sorted(observations, key=lambda o: (o[0], not o[1]))
    at_risk = len(obs)
    survival = 1.0
    curve: list[tuple[float, float]] = []
    i = 0
    while i < len(obs):
        t = obs[i][0]
        events = censored = 0
        while i < len(obs) and obs[i][0] == t:
            if obs[i][1]:
                events += 1
            else:
                censored += 1
            i += 1
        if events and at_risk:
            survival *= 1 - events / at_risk
            curve.append((t, survival))
        at_risk -= events + censored
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


def survival_summary(observations: list[tuple[float, bool]]) -> dict[str, float | int | None]:
    """Sintesi per la UI. ``medianDays`` None = metà degli annunci non si è
    ancora venduta nella finestra osservata (dato onesto, non un buco)."""
    curve = kaplan_meier(observations)
    events = sum(1 for _, sold in observations if sold)
    return {
        "medianDays": round(km_median(curve), 1) if km_median(curve) is not None else None,
        "sold7dPct": round(km_sold_by(curve, 7) * 100, 1),
        "sold30dPct": round(km_sold_by(curve, 30) * 100, 1),
        "events": events,
        "censored": len(observations) - events,
    }
