"""Matrice opportunità modello × guasto (C2, C3, C5 della release).

La domanda del business: *dove conviene cacciare?* Per ogni modello e ogni
guasto riparabile, dagli annunci ATTIVI:

- **acquisto tipico**: mediana (e 25° percentile = "buon affare") del prezzo
  chiesto per quel modello con SOLO quel guasto (+ eventuali segni estetici);
- **sconto vs sano** (C2): quanto costa in meno rispetto al sano originale;
- **riparazione**: ricambio (aftermarket o Apple, services/parts.py) + manodopera;
- **rivendita del riparato** (C3), misurata sul mercato:
  · con ricambio aftermarket: il sano del modello × il rapporto osservato tra
    sani con quella parte NON originale e sani tutti originali (stima per parte,
    da tutti i modelli: i dati per singolo modello sono pochi);
  · con ricambio Apple: il prezzo del sano originale (la parte è originale);
- **margine** e **ROI** nei due scenari, e il migliore;
- **volume**: quanti annunci così escono a settimana (dalla data di
  pubblicazione) → quante occasioni ci sono davvero;
- **potenziale €/settimana** = margine al prezzo "buono" (25° percentile) ×
  occasioni buone a settimana (un quarto del volume): l'ordinamento della
  matrice. Le celle con meno di 5 annunci vanno in fondo (fragili).

I guasti senza listino ricambi (Face ID, audio, ricarica, tasti) compaiono con
acquisto e sconto ma senza margine: il costo lo conosci tu.
Cache 5 minuti: scorre tutto lo stock attivo.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.database import get_db
from backend.scrapers.nlp_parser import _is_accessory_listing
from backend.services.parts import DEFECT_TO_PART, PART_LABEL, part_quote
from backend.services.variants import AUTO_ONLY_DEFECTS, HEALTHY_TIERS, iphone_model_key

# Guasti riparabili in matrice (codici NLP) e loro etichetta.
REPAIRABLE = {
    "schermo-rotto": "Schermo",
    "batteria-esausta": "Batteria",
    "back-rotto": "Scocca posteriore",
    "fotocamera-rotta": "Fotocamera",
    "face-id-rotto": "Face ID",
    "audio-rotto": "Audio / microfono",
    "ricarica-rotta": "Porta di ricarica",
    "tasti-rotti": "Tasti",
}
# Parte non originale (feature NLP) misurabile sul mercato, per ricambio.
NON_ORIGINAL_FEATURE = {"schermo": "Schermo-Non-Originale", "batteria": "Batteria-Non-Originale"}
# Ricambi aftermarket senza un segnale di mercato proprio:
# - scocca: il vetro posteriore non dà avvisi in iOS → nessuno sconto;
# - fotocamera: compare "parte sconosciuta" come per lo schermo → stesso sconto.
PROXY_RATIO = {"scocca": None, "fotocamera": "schermo"}
# Se il mercato non basta a misurare lo sconto di una parte, prudenza.
DEFAULT_RATIO = 0.85

MIN_HEALTHY = 5      # sani originali minimi per fidarsi della mediana
MIN_RATIO_N = 3      # sani con parte non originale per stimare un rapporto
FRAGILE_N = 5        # sotto, la cella è segnalata come fragile
WINDOW_DAYS = 28     # finestra per il volume settimanale

_CACHE_TTL_S = 300
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _median(values: list[float]) -> float | None:
    return statistics.median(values) if values else None


def _storage_breakdown(
    model: str, items: list[dict[str, Any]], healthy_by_storage: dict[tuple[str, int], list[float]]
) -> dict[str, Any]:
    """Sconto rotto vs sano A PARITÀ DI MEMORIA (G15 della release).

    Lo sconto della cella confronta la mediana dei rotti con quella dei sani:
    se i rotti sono più spesso 64/128 GB e i sani 256, lo sconto è gonfiato
    dalla memoria, non dal guasto. Qui per ogni taglio con abbastanza annunci
    (≥ 3 rotti, ≥ MIN_HEALTHY sani) e la media pesata sul mix dei rotti.
    """
    by_storage: dict[int, list[float]] = {}
    for i in items:
        if i.get("storage"):
            by_storage.setdefault(i["storage"], []).append(i["price"])
    rows, weighted, covered = [], 0.0, 0
    for storage, prices in sorted(by_storage.items()):
        healthy = healthy_by_storage.get((model, storage), [])
        if len(prices) < 3 or len(healthy) < MIN_HEALTHY:
            continue
        buy, sane = statistics.median(prices), statistics.median(healthy)
        rows.append({"storage": storage, "listings": len(prices), "healthySamples": len(healthy),
                     "buyMedian": round(buy), "healthyMedian": round(sane),
                     "discountEur": round(sane - buy)})
        weighted += (sane - buy) * len(prices)
        covered += len(prices)
    return {
        "byStorage": rows,
        # Solo se i tagli misurati coprono almeno metà dei rotti della cella.
        "discountSameStorageEur": (
            round(weighted / covered) if covered and covered >= len(items) / 2 else None
        ),
    }


def _p25(values: list[float]) -> float | None:
    if len(values) < 4:
        return min(values) if values else None
    return statistics.quantiles(sorted(values), n=4)[0]


def _load_rows() -> list[dict[str, Any]]:
    from backend.services.reads import _born, _cols, _row_model, _select_all  # noqa: PLC0415

    db = get_db()
    table = "live_opportunities_tech"
    rows = _select_all(
        lambda: db.table(table)
        .select(_cols(table, "id", "title", "variant_key", "target_id", "asking_price",
                      "condition_tier", "defects_noted", "features", "found_at", "status",
                      "storage_gb"))
        # Anche i rotti già spariti: sono le occasioni che qualcuno ha preso
        # davvero. Prezzi e mediane restano sugli attivi (vedi "active").
        .in_("status", ["nuovo", "visto", "venduto_rimosso", "scaduto"])
    )
    out = []
    for r in rows:
        if _is_accessory_listing(r.get("title")):
            continue
        model = _row_model(r, {})
        price = r.get("asking_price")
        if not model or not price or float(price) <= 0:
            continue
        defects = set(r.get("defects_noted") or []) - AUTO_ONLY_DEFECTS
        out.append({
            "model": model,
            "price": float(price),
            "tier": r.get("condition_tier") or "buono",
            "functional": defects - {"graffi"},
            "features": set(r.get("features") or []),
            "born": _born(r),
            "active": r.get("status") in ("nuovo", "visto"),
            "storage": r.get("storage_gb"),
        })
    return out


def _non_original_ratios(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Per parte: mediana tra modelli di (sano con parte non originale ÷ sano
    tutto originale). <1 = quanto vale meno un telefono riparato aftermarket."""
    healthy: dict[str, list[float]] = {}
    nonorig: dict[str, dict[str, list[float]]] = {p: {} for p in NON_ORIGINAL_FEATURE}
    for r in rows:
        if r["tier"] not in HEALTHY_TIERS or r["functional"]:
            continue
        flags = [p for p, f in NON_ORIGINAL_FEATURE.items() if f in r["features"]]
        if not flags:
            healthy.setdefault(r["model"], []).append(r["price"])
        elif len(flags) == 1:  # una sola parte non originale: effetto isolato
            nonorig[flags[0]].setdefault(r["model"], []).append(r["price"])
    out: dict[str, dict[str, Any]] = {}
    for part, by_model in nonorig.items():
        ratios = []
        samples = 0
        for model, prices in by_model.items():
            base = healthy.get(model, [])
            if len(prices) >= MIN_RATIO_N and len(base) >= MIN_HEALTHY:
                ratios.append(statistics.median(prices) / statistics.median(base))
                samples += len(prices)
        out[part] = {
            "ratio": round(statistics.median(ratios), 3) if ratios else DEFAULT_RATIO,
            "models": len(ratios),
            "samples": samples,
            "measured": bool(ratios),
        }
    return out


def get_repair_matrix(force: bool = False) -> dict[str, Any]:
    hit = _cache.get("tech")
    if hit and not force and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]

    all_rows = _load_rows()
    rows = [r for r in all_rows if r["active"]]
    ratios = _non_original_ratios(rows)
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    # Volume: annunci NATI nella finestra con quel solo guasto, in qualunque
    # stato (i rotti buoni spariscono in fretta: contarli solo da attivi
    # sottostimava proprio le occasioni migliori).
    born_recent: dict[tuple[str, str], int] = {}
    for r in all_rows:
        if len(r["functional"]) == 1 and r["born"] and r["born"] >= cutoff:
            key = (r["model"], next(iter(r["functional"])))
            born_recent[key] = born_recent.get(key, 0) + 1

    healthy_orig: dict[str, list[float]] = {}
    healthy_by_storage: dict[tuple[str, int], list[float]] = {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for r in rows:
        if r["tier"] in HEALTHY_TIERS and not r["functional"] and not any(
            f in r["features"] for f in NON_ORIGINAL_FEATURE.values()
        ):
            healthy_orig.setdefault(r["model"], []).append(r["price"])
            if r["storage"]:
                healthy_by_storage.setdefault((r["model"], r["storage"]), []).append(r["price"])
        # Un solo guasto funzionale riparabile, non venduto "per ricambi".
        if len(r["functional"]) == 1:
            code = next(iter(r["functional"]))
            if code in REPAIRABLE:
                groups.setdefault((r["model"], code), []).append(r)

    cells: list[dict[str, Any]] = []
    for (model, code), items in groups.items():
        base_prices = healthy_orig.get(model, [])
        if len(base_prices) < MIN_HEALTHY:
            continue
        healthy = statistics.median(base_prices)
        buy_prices = [i["price"] for i in items]
        buy = statistics.median(buy_prices)
        buy_good = _p25(buy_prices)
        weekly = round(born_recent.get((model, code), 0) / (WINDOW_DAYS / 7), 1)

        cell: dict[str, Any] = {
            "model": model,
            "modelKey": iphone_model_key(model),
            "defect": code,
            "defectLabel": REPAIRABLE[code],
            "listings": len(items),
            "weekly": weekly,
            "fragile": len(items) < FRAGILE_N,
            "healthyMedian": round(healthy),
            "healthySamples": len(base_prices),
            "buyMedian": round(buy),
            "buyGood": round(buy_good) if buy_good is not None else None,
            "discountEur": round(healthy - buy),
            "scenarios": {},
            "best": None,
        }
        part = DEFECT_TO_PART.get(code)
        if part:
            quote = part_quote(iphone_model_key(model), part)
            labor = quote["labor"]
            ratio_key = PROXY_RATIO.get(part, part)
            ratio = 1.0 if ratio_key is None else (ratios.get(ratio_key) or {}).get("ratio", DEFAULT_RATIO)
            scen = {}
            # Listino corretto dalle tue riparazioni (E3), come nella scheda.
            from backend.services.repair_feedback import part_correction  # noqa: PLC0415

            def corrected(price: float, source: str) -> float:
                corr = part_correction(part, source)
                return price * corr["ratio"] if corr else price

            if quote["aftermarket"]:
                cost = corrected(quote["aftermarket"]["price"], "aftermarket") + labor
                resale = healthy * ratio
                scen["aftermarket"] = {
                    "partCost": round(cost, 2), "grade": quote["aftermarket"]["grade"],
                    "resale": round(resale), "resaleRatio": ratio,
                }
            if quote["apple"]:
                cost = corrected(quote["apple"]["net"], "apple") + labor
                scen["apple"] = {"partCost": round(cost, 2), "resale": round(healthy), "resaleRatio": 1.0}
            for s in scen.values():
                s["margin"] = round(s["resale"] - buy - s["partCost"])
                s["marginAtGoodBuy"] = (
                    round(s["resale"] - buy_good - s["partCost"]) if buy_good is not None else None
                )
                invested = buy + s["partCost"]
                s["roiPct"] = round(s["margin"] / invested * 100, 1) if invested > 0 else None
            cell["part"] = PART_LABEL.get(part, part)
            cell["scenarios"] = scen
            if scen:
                best_key = max(scen, key=lambda k: scen[k]["margin"])
                best = scen[best_key]
                cell["best"] = {"source": best_key, **best}
        # Si compra solo il quarto più economico (≤ p25): il potenziale reale è il
        # margine a QUEL prezzo × quante occasioni così escono a settimana. Alla
        # mediana il mercato è già efficiente (margini piccoli).
        good_margin = (cell["best"] or {}).get("marginAtGoodBuy")
        cell["goodDealsWeekly"] = round(weekly / 4, 2)
        cell["weeklyPotentialEur"] = (
            round(max(good_margin, 0) * weekly / 4) if good_margin is not None else None
        )
        cell.update(_storage_breakdown(model, items, healthy_by_storage))
        cells.append(cell)

    cells.sort(key=lambda c: (c["fragile"], c["weeklyPotentialEur"] is None,
                              -(c["weeklyPotentialEur"] or 0), -c["listings"]))
    result = {
        "cells": cells,
        "nonOriginalRatios": ratios,
        "windowDays": WINDOW_DAYS,
        "computedAt": datetime.now(timezone.utc).isoformat(),
    }
    _cache["tech"] = (time.monotonic(), result)
    return result
