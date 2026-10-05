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

import re
from datetime import datetime, timezone
from typing import Any

# ---------------------- riparazioni (tech): SOLO ricambio Apple originale ----
#
# L'unico costo certo al 100% è il prezzo del RICAMBIO Apple ORIGINALE (Self
# Service Repair, solo pezzo). Escludiamo di proposito:
#   - manodopera: per la batteria la fai tu; per lo schermo è imprevedibile
#     (può andar liscio o dare problemi) → non stimabile;
#   - ricambi compatibili: il prezzo varia anche del 100% per marca/scelta.
# Solo sostituzioni STANDARD non complesse: schermo e batteria. Il vetro
# posteriore (rimozione laser) e il Face ID NON sono ricambi standard →
# restano solo flag di difetto, senza un costo inventato.
#
# ⚠️ Prezzi indicativi: AGGIORNARLI con i valori esatti del ricambio dal sito
# Apple (support.apple.com/self-service-repair). Variano per generazione: la
# tabella è per fascia modello, facile da affinare per singolo modello.
APPLE_PART_EUR: dict[str, dict[str, int]] = {
    # fascia:     schermo (display), batteria
    "base":    {"schermo-rotto": 290, "batteria-esausta": 70},
    "plus":    {"schermo-rotto": 350, "batteria-esausta": 75},
    "pro":     {"schermo-rotto": 330, "batteria-esausta": 75},
    "pro-max": {"schermo-rotto": 380, "batteria-esausta": 80},
}

_REPAIR_LABEL = {
    "schermo-rotto": "Schermo (ricambio Apple)",
    "batteria-esausta": "Batteria (ricambio Apple)",
}

# Difetti tech con sostituzione STANDARD → margine netto ricalcolabile.
# Ricambi con prezzo a listino (services/parts.py): lo schermo, la batteria e
# la scocca posteriore (solo aftermarket: Apple non la vende self-service).
REPAIRABLE_TECH_DEFECTS = ("schermo-rotto", "batteria-esausta", "back-rotto", "fotocamera-rotta")

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

# Tech: nessuna penalità inventata. I difetti non-riparabili con ricambio
# standard (Face ID, vetro posteriore, iCloud) sono già scontati dal fattore
# condizione ("difetti"/"rotto") nel valore equo — non aggiungiamo cifre incerte.
TECH_DEFECT_PENALTY_EUR: dict[str, int] = {}


def apply_config(cfg: dict[str, Any]) -> None:
    """Applica gli override runtime (dalle Impostazioni UI) alle tabelle di
    modulo, in place, così le funzioni pure ne leggono i nuovi valori:
    margine obiettivo per categoria e prezzi ricambi Apple per fascia."""
    tm = cfg.get("target_margin_pct")
    if isinstance(tm, dict):
        for k, v in tm.items():
            try:
                TARGET_MARGIN_PCT[k] = float(v)
            except (TypeError, ValueError):
                pass
    ap = cfg.get("apple_part_eur")
    if isinstance(ap, dict):
        for tier, parts in ap.items():
            if tier in APPLE_PART_EUR and isinstance(parts, dict):
                for pk, pv in parts.items():
                    if pk in APPLE_PART_EUR[tier]:
                        try:
                            APPLE_PART_EUR[tier][pk] = int(pv)
                        except (TypeError, ValueError):
                            pass


def _model_tier(title: str | None) -> str:
    t = (title or "").lower()
    if "pro max" in t:
        return "pro-max"
    if "plus" in t:
        return "plus"
    if "pro" in t:
        return "pro"
    return "base"


def repair_costs(
    category: str, title: str | None, defects: list[str]
) -> list[dict[str, Any]]:
    """Radar riparazioni (solo tech): una voce per ricambio con le DUE colonne
    (originale Apple al netto del credito di reso, aftermarket) e il ``cost``
    usato nei conti (colonna scelta nelle Impostazioni + manodopera).

    Listini per MODELLO (``services/parts.py``); se il modello non c'è in
    nessuno dei due si ripiega sulla vecchia tabella Apple per fascia."""
    if category == "automobile":
        return []
    from backend.services.parts import DEFECT_TO_PART, part_quote  # noqa: PLC0415
    from backend.services.variants import iphone_model_key  # noqa: PLC0415

    model_key = iphone_model_key(title)
    items: list[dict[str, Any]] = []
    for defect in defects:
        part = DEFECT_TO_PART.get(defect)
        if not part:
            continue
        quote = part_quote(model_key, part)
        if quote["cost"] is None:
            fallback = APPLE_PART_EUR[_model_tier(title)].get(defect)
            if fallback is None:
                continue  # niente listino per questo ricambio: nessuna cifra inventata
            quote = {**quote, "cost": float(fallback), "partCost": float(fallback),
                     "source": "apple-fascia"}
        items.append({"defect": defect, **quote})
    return items


def _track_record(category: str, defects: list[str]) -> dict[str, Any] | None:
    if category == "automobile" or not defects:
        return None
    from backend.services.defects import from_nlp  # noqa: PLC0415
    from backend.services.repair_feedback import guasto_success  # noqa: PLC0415

    return guasto_success(from_nlp(defects, [])["guasti"])


# Ricambio aftermarket → quale sconto di mercato si applica alla rivendita.
# La scocca non dà avvisi in iOS (nessuno sconto); la fotocamera sì, come lo schermo.
_RATIO_FOR_PART = {"schermo": "schermo", "batteria": "batteria", "fotocamera": "schermo", "scocca": None}


def repair_resale_factor(
    repairs: list[dict[str, Any]], ratios: dict[str, float] | None
) -> float:
    """Moltiplicatore sul prezzo del sano per il telefono riparato: prodotto
    degli sconti delle parti montate aftermarket (1.0 se tutte Apple)."""
    factor = 1.0
    for item in repairs:
        if item.get("source") != "aftermarket":
            continue
        key = _RATIO_FOR_PART.get(item.get("part", ""))
        if key and ratios and ratios.get(key):
            factor *= ratios[key]
    return round(factor, 3)


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


def max_bid(
    category: str,
    resale: float | None,
    penalty_eur: int = 0,
    repair_eur: int = 0,
    carry_eur: int = 0,
) -> int | None:
    """Prezzo d'acquisto MASSIMO per centrare il margine obiettivo (walk-away).

    A differenza di ``suggested_offer`` (apertura, sotto il richiesto), è il
    *tetto*: sopra questa cifra l'affare non rende abbastanza, a prescindere dal
    richiesto. Base = ``resale`` (prezzo di realizzo reale = mediana dei venduti
    della variante SANA), meno costi di riparazione/penalità, meno il margine
    obiettivo. Per i "rotti riparabili" ``resale`` è il prezzo del funzionante e
    ``repair_eur`` copre il ripristino.

    ``carry_eur`` = **deprezzamento maturato mentre lo tieni in magazzino** (curva
    di deprezzamento della variante × giorni attesi di vendita). È un costo reale
    dell'operazione come il ricambio: senza, il tetto è ottimista su tutto ciò
    che gira lento, che è proprio dove si perdono i soldi.
    """
    if resale is None or resale <= 0:
        return None
    target = TARGET_MARGIN_PCT.get(category, 15.0)
    step = OFFER_ROUNDING.get(category, 10)
    bid = resale * (1 - target / 100) - penalty_eur - repair_eur - carry_eur
    if bid <= 0:
        return None
    return int(bid // step * step)


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
    resale_ref: float | None = None,
    carry_month_eur: int | None = None,
    hold_days: int | None = None,
    non_original_ratios: dict[str, float] | None = None,
    acquisition: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Valutazione completa di un'opportunità per l'API (score + trattativa).

    ``acquisition`` (auto): costi d'acquisto (passaggio, agenzia, preparazione,
    services/car_costs.py), scalati dal tetto e dal margine netto.

    ``resale_ref`` = prezzo di realizzo del funzionante (mediana venduti sani);
    se assente si ripiega su ``market_avg``. Serve al ``maxBid`` (tetto d'acquisto).

    ``carry_month_eur`` (deprezzamento mensile della variante) e ``hold_days``
    (giorni attesi di vendita) danno il **costo di magazzino** dell'operazione,
    scontato dal tetto d'acquisto.
    """
    defects = defects or []
    urgency = urgency or []
    features = features or []

    repairs = repair_costs(category, title, defects)
    repair_total = sum(item["cost"] for item in repairs)
    penalty_total, penalty_breakdown = defect_penalty_eur(category, title, defects)

    resale = resale_ref if (resale_ref and resale_ref > 0) else market_avg
    if category == "automobile" and not (resale_ref and resale_ref > 0):
        # Auto senza valore equo affidabile: niente tetto né margine (la media
        # di un pool che mescola anni e versioni sarebbe un numero inventato).
        resale = None

    # Riparato con ricambi aftermarket: si rivende meno del sano tutto originale
    # (rapporto misurato sul mercato, services/repair_matrix.py). Con ricambio
    # Apple la parte è originale e il prezzo resta quello del sano.
    resale_factor = repair_resale_factor(repairs, non_original_ratios)
    if repairs and resale:
        resale = resale * resale_factor

    # Costo di magazzino: quanto si deprezza mentre resta invenduto.
    carry_total = 0
    if carry_month_eur and hold_days:
        carry_total = round(carry_month_eur * hold_days / 30)
    acq_total = (acquisition or {}).get("total") or 0
    bid = max_bid(category, resale, penalty_total, repair_total + acq_total, carry_total)
    # Auto: margine netto = rivendita attesa − richiesto − costi d'acquisto.
    car_net = (
        round(resale - asking - acq_total, 2)
        if category == "automobile" and acquisition and acquisition.get("total") is not None
        and resale and asking else None
    )

    # Margine netto post-riparazione (radar riparazioni): si rivende come SANO
    # riparato, quindi la base è il prezzo del sano (``resale``), non il valore
    # equo del rotto — che è già scontato per la condizione e farebbe contare
    # il guasto due volte (bug corretto il 2026-10-02).
    net_margin_eur: float | None = None
    net_margin_pct: float | None = None
    if repairs and resale is not None and asking is not None and asking > 0:
        net_margin_eur = round(resale - asking - repair_total - carry_total, 2)
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
                "resaleAfterRepair": round(resale) if resale else None,
                "resaleFactor": resale_factor,
                "netMarginEur": net_margin_eur,
                "netMarginPct": net_margin_pct,
            }
            if repairs
            else None
        ),
        # Quante delle TUE riparazioni con questo guasto sono riuscite (E3):
        # il guasto meno riuscito fra quelli dell'annuncio, solo con abbastanza
        # casi. Conta soprattutto per i "non si accende" (nessun ricambio noto).
        "repairTrackRecord": _track_record(category, defects),
        "defectPenaltyEur": penalty_total or None,
        "defectPenaltyBreakdown": penalty_breakdown or None,
        "suggestedOffer": suggested_offer(
            category, market_avg, asking, penalty_total, repair_total
        ),
        "maxBid": bid,
        "acquisitionCosts": acquisition,
        "netMarginAfterCostsEur": car_net,
        # True = conviene comprarlo anche al prezzo richiesto (asking ≤ tetto).
        "buyAtAsking": (
            bool(bid is not None and asking is not None and asking <= bid)
        ),
    }


# ------------------------------------------------------- Risk Score anti-frode
#
# Nel flipping di iPhone usati la prima causa di PERDITA TOTALE non è pagare
# troppo, ma comprare un telefono INVENDIBILE o non ricevere la merce. I segnali
# esistono già nei dati (difetti NLP, classe affare, tipo venditore); qui li
# aggreghiamo in un semaforo unico + il pattern-truffa a distanza che nessun
# altro modulo cattura (pagamento anticipato / solo spedizione / no resi).
# Funzione pura → testabile senza DB.

# Frasi tipiche della truffa "compra a distanza": pagamento anticipato senza
# tutele, niente ritiro/verifica di persona, circuiti non protetti.
_SCAM_TEXT_RE = re.compile(
    r"\b("
    r"solo\s+spedizion\w+|niente\s+ritiro|no\s+ritiro|no\s+incontr\w+|"
    r"pagamento\s+anticipat\w+|ricarica\s+postepay|bonifico\s+anticipat\w+|"
    r"paypal\s+amici|amici\s+e\s+parenti|no\s+res\w+|nessun\s+reso|"
    r"western\s+union|money\s*gram|solo\s+contrassegn\w+|"
    r"spedizione\s+prima\s+del\s+pagamento"
    r")\b",
    re.IGNORECASE,
)

# Segnali difetto che rendono il telefono NON un bene rivendibile come sano.
_UNSELLABLE_DEFECTS = frozenset({"icloud-bloccato", "per-ricambi", "da-riparare"})

_RISK_LABEL = {"alto": "🛑 Rischio alto", "medio": "⚠️ Rischio medio", "basso": "Rischio basso"}


# ------------------------------------------------------------------ auto

# Media italiana ~12–15.000 km/anno: sotto i 5.000 km/anno su un'auto di 4+
# anni il contachilometri va verificato (scalamento).
_LOW_KM_PER_YEAR = 5000
_LOW_KM_MIN_AGE = 4

_CAR_EVASIVE_RE = re.compile(
    r"\b(piccol\w* (?:urt\w*|bott\w*|ammaccatur\w*)|leggerment\w* (?:incidentat\w*|urtat\w*)|"
    # "da vedere" solo riferito a un componente: "Pronta da vedere e provare" è un invito.
    r"(?:motore|cambio|frizione|carrozzeria|dann[oi]|turbina)\s+da\s+(?:vedere|rivedere|sistemare|verificare)|"
    r"vendo cos[iì] com.?[eè]|cos[iì] com.?[eè]|senza garanzia|non garantisco|"
    r"per commercianti|solo commercianti|solo export\w*|per export|esportazione)\b",
    re.IGNORECASE,
)
_CAR_ADMIN_RE = re.compile(
    r"\b(fermo amministrativo|fermo fiscale|finanziament\w* (?:in corso|da (?:estinguere|saldare))|"
    r"rate da pagare|subentro|targa estera|targa (?:tedesca|francese|svizzera)|"
    r"documenti esteri|da (?:nazionalizzare|immatricolare)|senza documenti|"
    r"non circolante|radiat[ao]|ipoteca)\b",  # radiata/o, non "radiatore" (pezzo nuovo)
    re.IGNORECASE,
)


def car_risk_assessment(
    *,
    year: int | None,
    km: int | None,
    title: str | None,
    description: str | None,
    defects: list[str] | None,
    deal_class: str | None,
    seller_type: str | None = None,
    seller_active: int | None = None,
    has_images: bool = True,
    ref_year: int | None = None,
) -> dict[str, Any] | None:
    """Rischio di comprare QUESTA auto (Goal Version §8.5): km scalati,
    incidenti non dichiarati, fermo/finanziamento/provenienza estera, prezzo
    troppo basso, rivenditore travestito. Stessa forma di ``risk_assessment``.
    Nessun segnale → None. Con qualunque segnale, ricorda la visura PRA."""
    from datetime import datetime, timezone  # noqa: PLC0415

    text = " ".join(t for t in (title, description) if t)
    reasons: list[str] = []
    score = 0
    ref_year = ref_year or datetime.now(timezone.utc).year
    age = ref_year - int(year) if year else None

    if age is not None and km is not None and age >= _LOW_KM_MIN_AGE and km / age < _LOW_KM_PER_YEAR:
        score += 25
        reasons.append(f"Km bassi per l'età ({km // age:,} km/anno su {age} anni): verifica tagliandi "
                       f"e storico revisioni (scalamento contachilometri)".replace(",", "."))
    if km is None:
        score += 8
        reasons.append("Km non dichiarati")
    if _CAR_ADMIN_RE.search(text):
        # Con un fermo o un finanziamento attivo il passaggio non si fa: alto da solo.
        score += 45
        reasons.append("Possibile fermo amministrativo, finanziamento o provenienza estera: "
                       "visura PRA prima di muovere soldi")
    if _CAR_EVASIVE_RE.search(text):
        score += 15
        reasons.append("Linguaggio evasivo sullo stato (\"motore da vedere\", \"così com'è\", \"per commercianti\")")
    if "incidentata" in (defects or []):
        score += 20
        reasons.append("Incidentata dichiarata: valuta telaio e airbag, non solo la carrozzeria")
    if deal_class == "sospetto":
        score += 25
        reasons.append("Prezzo troppo basso per anno e km (possibile esca o problema nascosto)")
    if not has_images:
        score += 10
        reasons.append("Nessuna foto")
    if seller_type == "finto_privato" or (seller_active is not None and seller_active >= 2):
        score += 10
        reasons.append("Privato con più auto in vendita: probabile rivenditore senza garanzia legale")
    if text and _SCAM_TEXT_RE.search(text):
        score += 30
        reasons.append("Linguaggio da truffa a distanza (pagamento anticipato / no visione)")

    if score <= 0:
        return None
    reasons.append("Prima dell'acquisto: visura PRA (proprietari, fermi, ipoteche) e prova a freddo")
    level = "alto" if score >= 45 else "medio" if score >= 20 else "basso"
    return {"level": level, "label": _RISK_LABEL[level], "score": min(100, score), "reasons": reasons}


def risk_assessment(
    *,
    defects: list[str] | None,
    description: str | None,
    deal_class: str | None,
    ai_scam_high: bool = False,
    seller_type: str | None = None,
    seller_sold_count: int | None = None,
) -> dict[str, Any] | None:
    """Valuta il rischio di comprare *questo* annuncio (frode / invendibilità).

    Ritorna ``{"level", "label", "score", "reasons": [...]}`` oppure ``None`` se
    non c'è nessun segnale (così la UI non mostra un badge vuoto). Lo ``score``
    0–100 è la somma dei pesi dei segnali; il ``level`` è la soglia.
    """
    defects = defects or []
    reasons: list[str] = []
    score = 0

    # 1) iCloud bloccato = perdita quasi totale (telefono usabile solo a pezzi).
    if "icloud-bloccato" in defects:
        score += 45
        reasons.append("iCloud/blocco attivazione dichiarato — inservibile se non sbloccato")

    # 2) Pattern truffa a distanza dal testo (pagamento anticipato, no ritiro…).
    if description and _SCAM_TEXT_RE.search(description):
        score += 30
        reasons.append("Linguaggio da truffa a distanza (pagamento anticipato / no ritiro)")

    # 3) Prezzo troppo basso non giustificato (classe già declassata a sospetto),
    #    o AI che vede rischio truffa alto.
    if deal_class == "sospetto" or ai_scam_high:
        score += 25
        reasons.append("Prezzo troppo basso per il mercato (possibile truffa/errore)")

    # 4) Altri difetti che tolgono la rivendibilità come "sano".
    other = [d for d in defects if d in _UNSELLABLE_DEFECTS and d != "icloud-bloccato"]
    if other:
        score += 12
        reasons.append("Dichiarato per ricambi / da riparare (non rivendibile come sano)")

    # 5) Finto privato = rivenditore mascherato: non è frode, ma niente tutele da
    #    privato e prezzo spesso gonfiato → segnale minore.
    if seller_type == "finto_privato":
        score += 10
        reasons.append("Venditore finto-privato (rivenditore mascherato)")

    # 6) Venditore senza storico noto: sconosciuto, cautela in più.
    if seller_sold_count is not None and seller_sold_count == 0:
        score += 6
        reasons.append("Venditore senza vendite tracciate (storico ignoto)")

    if score <= 0:
        return None
    level = "alto" if score >= 45 else "medio" if score >= 20 else "basso"
    return {
        "level": level,
        "label": _RISK_LABEL[level],
        "score": min(100, score),
        "reasons": reasons,
    }
