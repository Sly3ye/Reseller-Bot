"""Profitto atteso per ora di lavoro (Goal Version §1.1).

Per chi compra, ripara e rivende da solo il collo di bottiglia è il tempo
(contatto, viaggio, riparazione, vendita), non il numero di occasioni.
Ordinare per margine per pezzo premia l'affare a 80 km; qui si ordina per
euro attesi per ora:

    €/ora = margine netto × P(riparazione riuscita) × P(ancora lì) ÷ ore

- ore = viaggio andata e ritorno (distanza da casa ÷ velocità media) +
  incontro + riparazione (minuti per pezzo) + vendita (+ pratiche per le auto);
- P(riparazione riuscita) = le TUE riparazioni con quel guasto (E3), solo con
  abbastanza casi; altrimenti 1;
- P(ancora lì quando arrivi) = ½^(tempo per arrivare ÷ emivita degli affari),
  solo con l'emivita misurata dal ricontrollo; altrimenti 1.

Le probabilità non misurate valgono 1: non si penalizza ciò che non si sa.
I tempi sono IPOTESI modificabili in Impostazioni (chiavi ``tv_*``) e si
tarano con i tempi veri registrati nella pipeline. Modulo puro (zero DB).
"""

from __future__ import annotations

from typing import Any

CONFIG: dict[str, Any] = {
    "tv_speed_kmh": 50,            # velocità media porta a porta
    "tv_meet_min": 20,             # incontro, verifica, pagamento
    "tv_sell_min": 45,             # foto, annuncio, messaggi, consegna della rivendita
    "tv_repair_min": {"schermo": 40, "batteria": 30, "scocca": 90, "fotocamera": 30},
    "tv_unknown_distance_km": 25,  # annuncio senza coordinate (o casa non impostata)
    "tv_car_extra_min": 240,       # auto: passaggio, preparazione, prove su strada
    "tv_arrange_min": 30,          # dal messaggio alla partenza (per P(ancora lì))
}
# Sotto questo campione l'emivita non si usa.
MIN_HALF_LIFE_SAMPLE = 20


def configure(cfg: dict[str, Any]) -> None:
    for key, value in cfg.items():
        if key not in CONFIG:
            continue
        if key == "tv_repair_min" and isinstance(value, dict):
            for part, minutes in value.items():
                try:
                    CONFIG["tv_repair_min"][part] = float(minutes)
                except (TypeError, ValueError):
                    pass
        else:
            try:
                CONFIG[key] = float(value)
            except (TypeError, ValueError):
                pass


def net_margin(item: dict[str, Any], category: str) -> float | None:
    """Il margine che conta per categoria e caso (stessi numeri della scheda)."""
    repair = item.get("repair") or {}
    if repair.get("netMarginEur") is not None:
        return float(repair["netMarginEur"])
    if category == "automobile":
        net = item.get("netMarginAfterCostsEur")
        return float(net) if net is not None else None
    margin = item.get("marginVsFairEur")
    if margin is None:
        return None
    carry = (item.get("carryCost") or {}).get("totalEur") or 0
    return float(margin) - float(carry)


def eligible(item: dict[str, Any]) -> bool:
    """Stesse regole degli alert: niente €/ora su sospetti (accessori, cloni,
    truffe: score 0), valutazioni da meno di 6 campioni o rischio alto, che in
    cima all'ordinamento finirebbero per "margini" da migliaia di euro."""
    return (item.get("dealClass") != "sospetto"
            and item.get("valuationConfidence") != "bassa"
            and (item.get("risk") or {}).get("level") != "alto")


def profit_per_hour(item: dict[str, Any], category: str,
                    half_life_min: float | None = None) -> dict[str, Any] | None:
    """{eurPerHour, hours, marginEur, minutes{...}, pRepair, pAvailable} o None
    se il margine non è stimabile o l'annuncio non è un candidato credibile."""
    if not eligible(item):
        return None
    margin = net_margin(item, category)
    if margin is None:
        return None
    km = item.get("distanceKm")
    distance_known = km is not None
    km = float(km) if distance_known else float(CONFIG["tv_unknown_distance_km"])
    speed = max(float(CONFIG["tv_speed_kmh"]), 1.0)
    one_way_min = km / speed * 60
    repair_min = sum(float(CONFIG["tv_repair_min"].get(r.get("part"), 0) or 0)
                     for r in (item.get("repair") or {}).get("items") or [])
    minutes = {
        "travel": round(2 * one_way_min),
        "meet": float(CONFIG["tv_meet_min"]),
        "repair": repair_min,
        "sell": float(CONFIG["tv_sell_min"]),
        "extra": float(CONFIG["tv_car_extra_min"]) if category == "automobile" else 0.0,
    }
    hours = max(sum(minutes.values()) / 60, 0.25)

    # Le tue riparazioni con quel guasto (repair_feedback.guasto_success: solo
    # con abbastanza casi; il guasto meno riuscito fra quelli dell'annuncio).
    record = item.get("repairTrackRecord") or {}
    p_repair = (round(float(record["successPct"]) / 100, 3)
                if item.get("repair") and record.get("successPct") is not None else None)
    p_available = None
    if half_life_min and half_life_min > 0:
        reach_min = float(CONFIG["tv_arrange_min"]) + one_way_min
        p_available = round(0.5 ** (reach_min / half_life_min), 3)
    expected = margin * (p_repair if p_repair is not None else 1) * (p_available if p_available is not None else 1)
    return {
        "eurPerHour": round(expected / hours, 1),
        "hours": round(hours, 2),
        "marginEur": round(margin, 2),
        "expectedEur": round(expected, 2),
        "minutes": {k: round(v) for k, v in minutes.items()},
        "distanceKnown": distance_known,
        "pRepair": p_repair,
        "pAvailable": p_available,
    }
