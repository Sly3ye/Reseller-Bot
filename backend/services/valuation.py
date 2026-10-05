"""Valutazione predittiva (Fase 2 BI): il valore equo del SINGOLO annuncio.

Sopra i bucket puliti della Fase 1 (varianti canoniche), qui si stima quanto
*dovrebbe* costare quel preciso annuncio dati i suoi attributi — non solo la
media della variante — e lo si colloca nella distribuzione di mercato, con la
distinzione cruciale **affare vs truffa**.

Metodo (leggero, solo ``statistics``, nessuna dipendenza pesante):
- **Riferimento** = mediana dei prezzi SANI della variante (robusta agli
  outlier). Per le **auto** il riferimento è il **prezzo atteso a QUELL'ETÀ e
  QUEI km** nella sua generazione (``fit_car_price_model``); senza un modello
  affidabile l'auto resta senza valore equo ("non so"), mai la mediana di un
  pool che mescola anni e km diversissimi.
- **Fattore condizione**: sposta il riferimento per la fascia dell'annuncio
  (come-nuovo sopra, difetti/rotto sotto).
- **Posizione**: percentile del prezzo richiesto nella distribuzione della
  variante (10 = più economico del 90% dei simili).
- **Classificazione**: ``affare`` / ``in-linea`` / ``caro`` / ``sospetto``.
  Il "sospetto" (troppo sotto il valore equo, spesso senza foto) separa gli
  affari veri dalle esche/errori di prezzo, così gli alert non ci cascano.

Funzioni pure → testabili senza DB.
"""

from __future__ import annotations

import math
import statistics
from datetime import datetime, timezone
from typing import Any

# Fattori di condizione: quanto vale un annuncio di quella fascia rispetto al
# riferimento "sano" della variante. Euristici, da tarare con la pipeline P&L.
_TECH_COND_FACTOR = {
    "come-nuovo": 1.08,
    "buono": 1.00,
    "difetti": 0.82,
    "rotto": 0.55,
}
_AUTO_COND_FACTOR = {
    "buono": 1.00,
    "difetti": 0.90,
    "incidentata": 0.60,
}

DEAL_MARGIN_PCT = 15.0     # margine vs valore equo per dichiarare "affare"
SUSPECT_RATIO = 0.55       # richiesto < equo*0.55 → troppo bello per essere vero
EXPENSIVE_RATIO = 1.15     # richiesto > equo*1.15 → "caro"
MIN_POOL = 3               # campioni minimi nella variante per valutare


# ------------------------------------------------------------- auto: età + km

CAR_MODEL_MIN_SAMPLES = 12   # annunci sani con anno e km, per generazione
CAR_MODEL_MAX_ERR_PCT = 35   # errore tipico oltre cui il modello non si usa
_OUTLIER_SD = 2.5            # residui oltre ±2.5 sd: fuori, e si rifà il fit


def _solve3(a: list[list[float]], b: list[float]) -> list[float] | None:
    """Sistema 3×3 per eliminazione di Gauss (equazioni normali)."""
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(3):
        pivot = max(range(col, 3), key=lambda r: abs(m[r][col]))
        if abs(m[pivot][col]) < 1e-12:
            return None
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(3):
            if r != col:
                f = m[r][col] / m[col][col]
                m[r] = [x - f * y for x, y in zip(m[r], m[col])]
    return [m[i][3] / m[i][i] for i in range(3)]


def _ols(points: list[tuple[float, float, float]]) -> list[float] | None:
    """log(prezzo) = a + b·età + c·(km/10.000): coefficienti [a, b, c]."""
    xtx = [[0.0] * 3 for _ in range(3)]
    xty = [0.0] * 3
    for age, km10k, y in points:
        x = (1.0, age, km10k)
        for i in range(3):
            xty[i] += x[i] * y
            for j in range(3):
                xtx[i][j] += x[i] * x[j]
    return _solve3(xtx, xty)


def fit_car_price_model(rows: list[tuple[int, int, float]], ref_year: int | None = None
                        ) -> dict[str, Any] | None:
    """Modello di prezzo di UNA generazione da annunci sani (anno, km, prezzo).

    Forma log-lineare: il deprezzamento è percentuale (un anno in più toglie
    circa il b% del valore, non una cifra fissa). Accettato solo se:
    - almeno CAR_MODEL_MIN_SAMPLES annunci dopo aver tolto gli anomali;
    - prezzo che SCENDE con età e km (coefficienti negativi: altrimenti i dati
      sono sporchi o il campione non copre abbastanza anni/km);
    - errore tipico ≤ CAR_MODEL_MAX_ERR_PCT.
    Ritorna coefficienti, campione, errore tipico % e intervallo coperto.
    """
    ref_year = ref_year or datetime.now(timezone.utc).year
    rows = [(y, normalize_km(k, y, ref_year), pr) for y, k, pr in rows]
    pts = [
        (float(ref_year - int(year)), float(km) / 10000.0, math.log(float(price)))
        for year, km, price in rows
        if year and km is not None and price and float(price) > 500 and 0 <= ref_year - int(year) <= 40
    ]
    for _ in range(2):  # fit, via gli anomali, rifit
        if len(pts) < CAR_MODEL_MIN_SAMPLES:
            return None
        coef = _ols(pts)
        if coef is None:
            return None
        resid = [y - (coef[0] + coef[1] * a + coef[2] * k) for a, k, y in pts]
        sd = statistics.pstdev(resid)
        kept = [p for p, r in zip(pts, resid) if abs(r) <= _OUTLIER_SD * sd] if sd > 0 else pts
        if len(kept) == len(pts):
            break
        pts = kept
    if len(pts) < CAR_MODEL_MIN_SAMPLES:
        return None
    coef = _ols(pts)
    if coef is None or coef[1] >= 0 or coef[2] >= 0:
        return None
    resid = [y - (coef[0] + coef[1] * a + coef[2] * k) for a, k, y in pts]
    err_pct = round((math.exp(statistics.pstdev(resid)) - 1) * 100, 1)
    if err_pct > CAR_MODEL_MAX_ERR_PCT:
        return None
    return {
        "coef": coef, "n": len(pts), "errPct": err_pct, "refYear": ref_year,
        "yearRange": (int(ref_year - max(a for a, _, _ in pts)), int(ref_year - min(a for a, _, _ in pts))),
        "kmRange": (int(min(k for _, k, _ in pts) * 10000), int(max(k for _, k, _ in pts) * 10000)),
        # Quanto vale in meno un anno / 10.000 km in più (in %), per la UI.
        "perYearPct": round((math.exp(coef[1]) - 1) * 100, 1),
        "per10kKmPct": round((math.exp(coef[2]) - 1) * 100, 1),
    }


def normalize_km(km: int | None, year: int | None, ref_year: int | None = None) -> int | None:
    """Km scritti in migliaia ("184" per 184.000, comune nel campo km di
    Subito): sotto 1.000 km un'auto con più di 2 anni non è credibile, quindi
    si moltiplica per mille. Un'auto davvero km 0 è recente e resta com'è."""
    if km is None:
        return None
    ref_year = ref_year or datetime.now(timezone.utc).year
    if 0 < km < 1000 and year and ref_year - int(year) >= 2:
        return km * 1000
    return km


def car_expected_price(model: dict[str, Any] | None, year: int | None, km: int | None) -> float | None:
    """Prezzo atteso di un'auto sana di quell'anno e km, o None. Fuori
    dall'intervallo coperto dal campione (con un po' di margine) non si
    estrapola: un 2007 da 300.000 km stimato con dati 2015-2019 è un'invenzione."""
    if not model or not year or km is None:
        return None
    km = normalize_km(km, year, model.get("refYear"))
    lo_y, hi_y = model["yearRange"]
    lo_k, hi_k = model["kmRange"]
    if not (lo_y - 1 <= int(year) <= hi_y + 1) or not (lo_k * 0.8 - 10000 <= km <= hi_k * 1.2 + 10000):
        return None
    a, b, c = model["coef"]
    return round(math.exp(a + b * (model["refYear"] - int(year)) + c * km / 10000.0), 2)


def _condition_factor(category: str, tier: str | None) -> float:
    table = _AUTO_COND_FACTOR if category == "automobile" else _TECH_COND_FACTOR
    return table.get(tier or "buono", 1.0)


def price_position(asking: float | None, prices: list[float]) -> float | None:
    """Percentile (0–100) del prezzo richiesto nella variante.

    10 → più economico del 90% dei simili (coda degli affari); 90 → tra i più cari.
    """
    vals = sorted(p for p in prices if p and p > 0)
    if asking is None or len(vals) < MIN_POOL:
        return None
    below = sum(1 for v in vals if v < asking)
    return round(below / len(vals) * 100, 1)


def estimate_fair_value(
    *,
    category: str,
    condition_tier: str | None,
    variant_prices: list[float],
    km: int | None = None,
    year: int | None = None,
    car_model: dict[str, Any] | None = None,
    sold_reference: float | None = None,
    sold_reference_is_tier_specific: bool = False,
) -> float | None:
    """Prezzo equo atteso per questo annuncio. None se dati insufficienti.

    Riferimento (dal migliore al fallback):
      1. **auto**: SOLO il prezzo atteso a quell'età e quei km nella sua
         generazione (``car_expected_price``); senza → None ("non so");
      2. **mediana dei VENDUTI** della variante (``sold_reference``): il prezzo
         di realizzo reale, non quello listato (evita la sovrastima da vetrina);
      3. mediana dei prezzi SANI **listati** della variante (fallback finché i
         venduti non si accumulano).

    Il **fattore condizione** (sopra/sotto per come-nuovo/difetti) si applica
    solo quando il riferimento NON riflette già questa fascia: se
    ``sold_reference_is_tier_specific`` è True, ``sold_reference`` è già "il
    prezzo a cui si vende un come-nuovo di questa variante" — moltiplicarlo di
    nuovo per il fattore condizione conterebbe l'aggiustamento due volte e
    gonfierebbe il valore equo (bug osservato: quasi sempre troppo alto).
    """
    if category == "automobile":
        # Mediana o venduti di un pool auto mescolano anni e km: niente ripieghi.
        expected = car_expected_price(car_model, year, km)
        if expected is None:
            return None
        return round(expected * _condition_factor(category, condition_tier), 2)

    healthy = sorted(p for p in variant_prices if p and p > 0)
    base: float | None = statistics.median(healthy) if len(healthy) >= MIN_POOL else None
    apply_condition_factor = True

    # I venduti battono i listati come riferimento (prezzo di realizzo reale).
    if sold_reference and sold_reference > 0:
        base = sold_reference
        apply_condition_factor = not sold_reference_is_tier_specific

    if base is None or base <= 0:
        return None
    factor = _condition_factor(category, condition_tier) if apply_condition_factor else 1.0
    return round(base * factor, 2)


def evaluate_value(
    *,
    category: str,
    asking: float | None,
    condition_tier: str | None,
    variant_prices: list[float],
    km: int | None = None,
    year: int | None = None,
    car_model: dict[str, Any] | None = None,
    sold_reference: float | None = None,
    sold_reference_is_tier_specific: bool = False,
    has_images: bool = True,
) -> dict[str, Any]:
    """Valutazione completa: valore equo, margine vs equo, posizione, classe.

    Ritorna sempre le chiavi (con None dove non calcolabile) per un consumo
    uniforme lato reads/API. ``fairValueSource`` dichiara su cosa poggia il
    valore equo: ``eta-km`` (modello auto per generazione), ``venduti``
    (realizzo reale) o ``listati`` (fallback). Per le auto c'è anche
    ``fairValueErrPct``, l'errore tipico del modello: un "affare" deve
    superare sia la soglia sia quell'errore.
    """
    fair = estimate_fair_value(
        category=category,
        condition_tier=condition_tier,
        variant_prices=variant_prices,
        km=km,
        year=year,
        car_model=car_model,
        sold_reference=sold_reference,
        sold_reference_is_tier_specific=sold_reference_is_tier_specific,
    )
    position = price_position(asking, variant_prices)

    if category == "automobile":
        source = "eta-km"
    elif sold_reference and sold_reference > 0:
        source = "venduti"
    else:
        source = "listati"

    result: dict[str, Any] = {
        "fairValue": fair,
        "fairValueSource": source if fair is not None else None,
        "pricePosition": position,
        "marginVsFairEur": None,
        "marginVsFairPct": None,
        "dealClass": "n/d",
        "fairValueErrPct": (car_model or {}).get("errPct") if category == "automobile" and fair else None,
    }
    if fair is None or asking is None or asking <= 0:
        return result

    margin = fair - asking
    margin_pct = round(margin / asking * 100, 1)
    ratio = asking / fair
    result["marginVsFairEur"] = round(margin, 2)
    result["marginVsFairPct"] = margin_pct

    if ratio < SUSPECT_RATIO:
        deal_class = "sospetto"            # troppo sotto: probabile esca/errore
    elif margin_pct >= max(DEAL_MARGIN_PCT, result["fairValueErrPct"] or 0):
        # Auto: lo scarto deve superare anche l'errore tipico del modello,
        # altrimenti è rumore della stima e non un affare.
        deal_class = "affare"
    elif ratio > EXPENSIVE_RATIO:
        deal_class = "caro"
    else:
        deal_class = "in-linea"

    # Rinforzo anti-truffa: prezzo stracciato E nessuna foto → sospetto.
    if deal_class == "affare" and ratio < 0.65 and not has_images:
        deal_class = "sospetto"

    result["dealClass"] = deal_class
    return result
