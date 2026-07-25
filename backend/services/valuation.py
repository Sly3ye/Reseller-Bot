"""Valutazione predittiva (Fase 2 BI): il valore equo del SINGOLO annuncio.

Sopra i bucket puliti della Fase 1 (varianti canoniche), qui si stima quanto
*dovrebbe* costare quel preciso annuncio dati i suoi attributi — non solo la
media della variante — e lo si colloca nella distribuzione di mercato, con la
distinzione cruciale **affare vs truffa**.

Metodo (leggero, solo ``statistics``, nessuna dipendenza pesante):
- **Riferimento** = mediana dei prezzi SANI della variante (robusta agli
  outlier). Per le **auto**, se disponibile il modello prezzo~km, il
  riferimento diventa il **prezzo atteso a QUEI km** (elemento edonico).
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

import statistics
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
    km_model: tuple[float, float, int] | None = None,
) -> float | None:
    """Prezzo equo atteso per questo annuncio. None se dati insufficienti."""
    healthy = sorted(p for p in variant_prices if p and p > 0)
    base: float | None = statistics.median(healthy) if len(healthy) >= MIN_POOL else None

    # Auto: il riferimento migliore è il prezzo atteso a QUESTI km (edonico).
    if category == "automobile" and km_model and km:
        slope, intercept, _n = km_model
        km_expected = intercept + slope * km
        if km_expected > 0:
            base = km_expected

    if base is None or base <= 0:
        return None
    return round(base * _condition_factor(category, condition_tier), 2)


def evaluate_value(
    *,
    category: str,
    asking: float | None,
    condition_tier: str | None,
    variant_prices: list[float],
    km: int | None = None,
    km_model: tuple[float, float, int] | None = None,
    has_images: bool = True,
) -> dict[str, Any]:
    """Valutazione completa: valore equo, margine vs equo, posizione, classe.

    Ritorna sempre le chiavi (con None dove non calcolabile) per un consumo
    uniforme lato reads/API.
    """
    fair = estimate_fair_value(
        category=category,
        condition_tier=condition_tier,
        variant_prices=variant_prices,
        km=km,
        km_model=km_model,
    )
    position = price_position(asking, variant_prices)

    result: dict[str, Any] = {
        "fairValue": fair,
        "pricePosition": position,
        "marginVsFairEur": None,
        "marginVsFairPct": None,
        "dealClass": "n/d",
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
    elif margin_pct >= DEAL_MARGIN_PCT:
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
