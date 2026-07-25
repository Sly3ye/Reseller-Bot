"""Deal Score & assistente di trattativa (euristiche trasparenti, zero ML).

Il margine % da solo non basta a ordinare il feed: un +25% su un annuncio di
un finto privato, vecchio di 3 settimane e "da rivedere" vale meno di un +18%
pubblicato un'ora fa da un privato che "svende causa trasferimento". Questo
modulo combina i segnali già raccolti (margine, urgenza, tipo venditore,
difetti, freschezza, calo prezzo, corredo, batteria) in un punteggio 0–100
con breakdown leggibile, e produce i numeri per la trattativa:

- ``repair``          → radar riparazioni: per i difetti riparabili (schermo,
                        batteria, scocca) stima il costo e ricalcola il
                        margine NETTO post-riparazione.
- ``defect_penalty``  → penalità in € dei difetti dichiarati (sconto atteso).
- ``suggested_offer`` → prezzo di apertura consigliato al venditore.

Tutte le cifre sono euristiche dichiarate nelle tabelle qui sotto: si
correggono con l'esperienza reale registrata nella pipeline P&L (deals).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

# ------------------------------------------------- costi riparazione (tech)

# Riparazioni standard iPhone (ricambi compatibili, lab indipendente).
BATTERY_REPLACEMENT_EUR = 79
BACK_GLASS_EUR = 120

# Schermo: dipende dalla fascia del modello (dal titolo dell'annuncio).
SCREEN_BASE_EUR = 150          # modelli base (11, 12, 13, 14 "liscio", SE)
SCREEN_PRO_EUR = 240           # Pro
SCREEN_PRO_MAX_EUR = 300       # Pro Max / Plus

# ------------------------------------------------ penalità difetti (in €)

AUTO_DEFECT_PENALTY_EUR: dict[str, int] = {
    "frizione": 800,
    "graffi": 300,
    "grandine": 1000,
    "da-rivedere": 500,
    "spia-motore": 700,
    # incidentata/fuso sono esclusi dal mercato del "sano": penalità solo
    # indicativa, il margine contro la media resta fittizio.
    "incidentata": 3000,
    "fuso": 4000,
}

TECH_DEFECT_PENALTY_EUR: dict[str, int] = {
    "face-id-rotto": 150,      # riparazione difficile → sconto secco
    "batteria-esausta": BATTERY_REPLACEMENT_EUR,
    "back-rotto": BACK_GLASS_EUR,
    # schermo-rotto calcolato dinamicamente dal modello (vedi repair_costs).
}

# Difetti tech con riparazione standard → margine netto ricalcolabile.
REPAIRABLE_TECH_DEFECTS = ("schermo-rotto", "batteria-esausta", "back-rotto")


def _screen_cost_for(title: str | None) -> int:
    t = (title or "").lower()
    if "pro max" in t or "plus" in t:
        return SCREEN_PRO_MAX_EUR
    if "pro" in t:
        return SCREEN_PRO_EUR
    return SCREEN_BASE_EUR


def repair_costs(
    category: str, title: str | None, defects: list[str]
) -> list[dict[str, Any]]:
    """Radar riparazioni (solo tech): [{defect, label, cost}] per i riparabili."""
    if category == "automobile":
        return []
    items: list[dict[str, Any]] = []
    for defect in defects:
        if defect == "schermo-rotto":
            items.append(
                {
                    "defect": defect,
                    "label": "Sostituzione schermo",
                    "cost": _screen_cost_for(title),
                }
            )
        elif defect == "batteria-esausta":
            items.append(
                {
                    "defect": defect,
                    "label": "Sostituzione batteria",
                    "cost": BATTERY_REPLACEMENT_EUR,
                }
            )
        elif defect == "back-rotto":
            items.append(
                {
                    "defect": defect,
                    "label": "Vetro posteriore",
                    "cost": BACK_GLASS_EUR,
                }
            )
    return items


def defect_penalty_eur(
    category: str, title: str | None, defects: list[str]
) -> tuple[int, dict[str, int]]:
    """Somma delle penalità (€) dei difetti dichiarati, con breakdown.

    I difetti riparabili tech NON entrano qui (hanno il costo riparazione
    esplicito nel radar): evita il doppio conteggio nello suggested_offer.
    """
    table = (
        AUTO_DEFECT_PENALTY_EUR
        if category == "automobile"
        else TECH_DEFECT_PENALTY_EUR
    )
    breakdown: dict[str, int] = {}
    for defect in defects:
        if category != "automobile" and defect in REPAIRABLE_TECH_DEFECTS:
            continue
        amount = table.get(defect)
        if amount:
            breakdown[defect] = amount
    return sum(breakdown.values()), breakdown


# ---------------------------------------------------------- offerta suggerita

# Margine obiettivo sul prezzo di rivendita (media di mercato) per coprire
# tempo, rischio e costi di transazione.
TARGET_MARGIN_PCT = {"automobile": 15.0, "smartphone": 18.0}
OFFER_ROUNDING = {"automobile": 50, "smartphone": 10}


def suggested_offer(
    category: str,
    market_avg: float | None,
    asking: float | None,
    penalty_eur: int = 0,
    repair_eur: int = 0,
) -> int | None:
    """Prezzo di apertura consigliato per la trattativa.

    Formula: media_mercato × (1 − margine_obiettivo) − penalità difetti −
    costi riparazione, arrotondata verso il basso. Mai sopra il richiesto:
    se il calcolo supera l'asking (annuncio già stra-conveniente), si apre
    comunque un gradino sotto il richiesto per non lasciare soldi sul tavolo.
    """
    if market_avg is None or market_avg <= 0:
        return None
    target = TARGET_MARGIN_PCT.get(category, 15.0)
    step = OFFER_ROUNDING.get(category, 10)

    offer = market_avg * (1 - target / 100) - penalty_eur - repair_eur
    if asking is not None and asking > 0:
        just_below_asking = asking * 0.93
        offer = min(offer, just_below_asking)
    if offer <= 0:
        return None
    return int(offer // step * step)


# ------------------------------------------------------------------ score

def _freshness_points(found_at: str | None) -> int:
    if not found_at:
        return 0
    try:
        found = datetime.fromisoformat(str(found_at).replace("Z", "+00:00"))
    except ValueError:
        return 0
    hours = (datetime.now(timezone.utc) - found).total_seconds() / 3600
    if hours <= 2:
        return 12
    if hours <= 24:
        return 8
    if hours <= 72:
        return 4
    return 0


def deal_score(
    *,
    category: str,
    margin_pct: float | None,
    found_at: str | None,
    seller_type: str | None,
    defects: list[str],
    urgency: list[str],
    features: list[str],
    battery_pct: int | None,
    has_price_drop: bool,
) -> dict[str, Any]:
    """Punteggio 0–100 con breakdown leggibile [{label, points}].

    Il margine pesa fino a 55 punti (satura a +33%); il resto sono segnali
    di contesto che spostano un affare da "numericamente buono" a "buono
    davvero e trattabile adesso".
    """
    breakdown: list[dict[str, Any]] = []
    score = 0.0

    if margin_pct is not None and margin_pct > 0:
        pts = min(margin_pct, 33.0) / 33.0 * 55.0
        score += pts
        breakdown.append({"label": f"Margine +{margin_pct:.0f}%", "points": round(pts)})

    fresh = _freshness_points(found_at)
    if fresh:
        score += fresh
        breakdown.append({"label": "Annuncio fresco", "points": fresh})

    if urgency:
        score += 8
        breakdown.append(
            {"label": f"Urgenza ({', '.join(urgency)})", "points": 8}
        )

    seller_pts = {"privato": 8, "finto_privato": 2}.get(str(seller_type), 0)
    if seller_type:
        score += seller_pts
        breakdown.append(
            {"label": f"Venditore {seller_type}", "points": seller_pts}
        )

    if has_price_drop:
        score += 8
        breakdown.append({"label": "Prezzo già ribassato", "points": 8})

    if defects:
        malus = -min(4 * len(defects), 12)
        score += malus
        breakdown.append(
            {"label": f"Difetti ({', '.join(defects)})", "points": malus}
        )

    if category != "automobile" and battery_pct is not None:
        if battery_pct >= 90:
            score += 3
            breakdown.append({"label": f"Batteria {battery_pct}%", "points": 3})
        elif battery_pct < 85:
            score -= 3
            breakdown.append({"label": f"Batteria {battery_pct}%", "points": -3})

    corredo = [f for f in features if f in ("Scatola", "Fattura", "Garanzia-Apple")]
    if corredo:
        pts = min(2 * len(corredo), 4)
        score += pts
        breakdown.append({"label": f"Corredo ({', '.join(corredo)})", "points": pts})

    return {"score": max(0, min(100, round(score))), "breakdown": breakdown}


def evaluate_opportunity(
    *,
    category: str,
    title: str | None,
    asking: float | None,
    market_avg: float | None,
    margin_pct: float | None,
    found_at: str | None,
    seller_type: str | None,
    defects: list[str] | None,
    urgency: list[str] | None,
    features: list[str] | None,
    battery_pct: int | None,
    has_price_drop: bool,
) -> dict[str, Any]:
    """Valutazione completa di un'opportunità per l'API (score + trattativa)."""
    defects = defects or []
    urgency = urgency or []
    features = features or []

    repairs = repair_costs(category, title, defects)
    repair_total = sum(item["cost"] for item in repairs)
    penalty_total, penalty_breakdown = defect_penalty_eur(category, title, defects)

    # Margine netto post-riparazione (radar riparazioni): per i "rotti
    # riparabili" il vero margine è contro la media del funzionante, meno il
    # costo del ricambio.
    net_margin_eur: float | None = None
    net_margin_pct: float | None = None
    if repairs and market_avg is not None and asking is not None and asking > 0:
        net_margin_eur = round(market_avg - asking - repair_total, 2)
        net_margin_pct = round(net_margin_eur / (asking + repair_total) * 100, 1)

    score_input_margin = net_margin_pct if net_margin_pct is not None else margin_pct
    scored = deal_score(
        category=category,
        margin_pct=score_input_margin,
        found_at=found_at,
        seller_type=seller_type,
        defects=defects,
        urgency=urgency,
        features=features,
        battery_pct=battery_pct,
        has_price_drop=has_price_drop,
    )

    return {
        "score": scored["score"],
        "scoreBreakdown": scored["breakdown"],
        "repair": (
            {
                "items": repairs,
                "total": repair_total,
                "netMarginEur": net_margin_eur,
                "netMarginPct": net_margin_pct,
            }
            if repairs
            else None
        ),
        "defectPenaltyEur": penalty_total or None,
        "defectPenaltyBreakdown": penalty_breakdown or None,
        "suggestedOffer": suggested_offer(
            category, market_avg, asking, penalty_total, repair_total
        ),
    }
