"""Curva di deprezzamento per variante — *quanto perde di valore, e quanto in fretta*.

Il trend storico di ``market_trends`` risponde a "come si è mosso il prezzo di
QUESTO modello negli ultimi giorni", e serve mesi di storico prima di dire
qualcosa. Qui rispondiamo alla domanda che i dati di oggi sostengono già:

    **quanto vale un iPhone in funzione di quanti anni ha**, e quanto costa
    tenerlo in magazzino un mese in più.

Metodo (cross-sezionale, non longitudinale): a parità di **linea** (base / mini
/ Plus / Pro / Pro Max / "e") e di **taglio di memoria**, i modelli in vendita
oggi sono lo stesso oggetto a età diverse. La mediana del 14 Pro 256GB di oggi è
la miglior stima di quanto varrà il 15 Pro 256GB fra un anno. Da lì:

- **perdita a 12 mesi** (€ e %) = salto di prezzo verso la generazione precedente,
  annualizzato sulla distanza d'età reale fra le due;
- **costo di magazzino** (€/mese) = quella perdita ÷ 12 — il capitale che
  evapora mentre l'annuncio è fermo, da leggere insieme alla liquidità;
- **valore residuo %** rispetto al modello più recente della stessa linea →
  il confronto fra modelli richiesto dalla visione.

Le date di uscita non sono una tabella da mantenere: gli iPhone escono a
settembre dell'anno ``2008 + numero`` (12→2020, 13→2021 … 17→2025) e la linea
"e" a febbraio. La regola vale anche per i modelli futuri, quindi la curva non
va aggiornata a mano a ogni keynote. Uno scarto di qualche settimana è
irrilevante su una scala in anni.
"""

from __future__ import annotations

import re
import statistics
from datetime import date
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # import pesante solo per i tipi: build_curves resta puro
    from backend.core.database import Client

# Campione minimo per fidarsi della mediana di una variante.
MIN_SAMPLE = 3
# Distanza d'età massima (anni) fra due generazioni perché il confronto abbia
# senso come "perdita in 12 mesi": oltre, il salto è troppo lungo per annualizzare.
MAX_GEN_GAP_YEARS = 3.0

# iphone-15-pro-max-256 → (15, "pro-max", 256); iphone-16e-128 → (16, "e", 128).
_VARIANT_RE = re.compile(
    r"^iphone-(\d+)(e)?(?:-(mini|plus|air|pro-max|pro))?-(\d+|na)$"
)

_LINE_LABELS = {
    "": "Base",
    "mini": "mini",
    "plus": "Plus",
    "air": "Air",
    "pro": "Pro",
    "pro-max": "Pro Max",
    "e": "e",
}


def _release_date(number: int, line: str) -> date:
    """Uscita del modello: settembre dell'anno ``2008 + numero`` (12→2020, 13→2021
    … 17→2025). La linea "e" arriva a febbraio dell'anno DOPO il numerato che
    porta lo stesso numero: il 16e è di febbraio 2025, non 2024.

    Regola, non tabella: vale anche per i modelli non ancora usciti."""
    if line == "e":
        return date(2009 + number, 2, 1)
    return date(2008 + number, 9, 1)


def _parse_variant(variant_key: str) -> tuple[int, str, int | None] | None:
    """(numero, linea, memoria) da una variant_key iPhone; None se non parsabile."""
    match = _VARIANT_RE.match(variant_key or "")
    if not match:
        return None
    number, e_suffix, line, storage = match.groups()
    return (
        int(number),
        "e" if e_suffix else (line or ""),
        None if storage == "na" else int(storage),
    )


def _storage_label(storage: int | None) -> str:
    if storage is None:
        return "tutte"
    return "1TB" if storage >= 1024 else f"{storage}GB"


def _model_key(number: int, line: str) -> str:
    """Chiave modello allineata a quella del feed (``_model_key`` in reads.py),
    così un punto della curva si può usare come filtro sugli annunci."""
    if line == "e":
        return f"iphone-{number}e"
    return f"iphone-{number}-{line}" if line else f"iphone-{number}"


def _model_name(number: int, line: str) -> str:
    if line == "e":
        return f"iPhone {number}e"
    suffix = {
        "pro-max": " Pro Max",
        "pro": " Pro",
        "plus": " Plus",
        "mini": " mini",
        "air": " Air",
    }
    return f"iPhone {number}{suffix.get(line, '')}"


def build_curves(
    pools: dict[str, list[float]], today: date | None = None
) -> dict[str, Any]:
    """Costruisce curve e metriche dai pool di prezzo per variante.

    Puro (nessun DB) → testabile: ``pools`` è {variant_key: [prezzi sani]}.
    """
    today = today or date.today()

    # Un punto per (linea, memoria, modello); in più la serie "tutte le memorie",
    # che tiene in piedi la curva anche dove il singolo taglio ha pochi annunci.
    by_series: dict[tuple[str, int | None], dict[int, dict[str, Any]]] = {}
    merged: dict[tuple[str, int], list[float]] = {}

    for variant_key, prices in pools.items():
        parsed = _parse_variant(variant_key)
        if parsed is None or len(prices) < MIN_SAMPLE:
            continue
        number, line, storage = parsed
        merged.setdefault((line, number), []).extend(prices)
        if storage is None:
            continue
        by_series.setdefault((line, storage), {})[number] = {
            "median": round(statistics.median(prices)),
            "sample": len(prices),
        }

    for (line, number), prices in merged.items():
        if len(prices) < MIN_SAMPLE:
            continue
        by_series.setdefault((line, None), {})[number] = {
            "median": round(statistics.median(prices)),
            "sample": len(prices),
        }

    curves: list[dict[str, Any]] = []
    models: list[dict[str, Any]] = []

    for (line, storage), by_number in sorted(
        by_series.items(), key=lambda kv: (kv[0][0], kv[0][1] or 0)
    ):
        # Dal più recente al più vecchio: l'età cresce scendendo nella serie.
        numbers = sorted(by_number, reverse=True)
        if len(numbers) < 2:
            continue  # una curva con un solo punto non è una curva

        newest_median = by_number[numbers[0]]["median"]
        points: list[dict[str, Any]] = []

        for index, number in enumerate(numbers):
            entry = by_number[number]
            released = _release_date(number, line)
            age = round((today - released).days / 365.25, 2)
            median = entry["median"]

            # Generazione precedente (stessa linea e memoria) = "questo modello
            # fra un anno", da cui la perdita attesa annualizzata.
            loss_year_eur = loss_year_pct = loss_month_eur = None
            older_model = None
            if index + 1 < len(numbers):
                older_number = numbers[index + 1]
                older = by_number[older_number]
                # Arrotondato al decimo d'anno: fra due generazioni "a un anno"
                # ballano i giorni bisestili, e non vogliamo che una perdita di
                # 300€ diventi 299 per colpa del 29 febbraio.
                gap = round(
                    (released - _release_date(older_number, line)).days / 365.25, 1
                )
                if 0 < gap <= MAX_GEN_GAP_YEARS and median > 0:
                    loss_year_eur = round((median - older["median"]) / gap)
                    loss_year_pct = round(loss_year_eur / median * 100, 1)
                    loss_month_eur = round(loss_year_eur / 12)
                    older_model = _model_name(older_number, line)

            point = {
                "modelKey": _model_key(number, line),
                "model": _model_name(number, line),
                "line": line,
                "lineLabel": _LINE_LABELS.get(line, line),
                "storage": storage,
                "storageLabel": _storage_label(storage),
                "ageYears": age,
                "releasedAt": released.isoformat(),
                "median": median,
                "sample": entry["sample"],
                # Valore residuo rispetto al modello più recente della linea:
                # il confronto diretto fra generazioni.
                "retentionPct": (
                    round(median / newest_median * 100, 1) if newest_median else None
                ),
                # Perdita attesa nei prossimi 12 mesi (dalla generazione prima).
                "loss12mEur": loss_year_eur,
                "loss12mPct": loss_year_pct,
                # Costo di tenere fermo un pezzo: € bruciati ogni mese.
                "carryCostMonthEur": loss_month_eur,
                "vsModel": older_model,
            }
            points.append(point)
            if storage is not None:
                models.append(point)

        curves.append(
            {
                "line": line,
                "lineLabel": _LINE_LABELS.get(line, line),
                "storage": storage,
                "storageLabel": _storage_label(storage),
                "points": points,
                "sample": sum(p["sample"] for p in points),
            }
        )

    return {"curves": curves, "models": models}


def _summary(models: list[dict[str, Any]]) -> dict[str, Any]:
    """Chi tiene il valore e chi lo brucia — la lettura in una riga."""
    rated = [m for m in models if m.get("loss12mPct") is not None]
    if not rated:
        return {"best": None, "worst": None, "avgLoss12mPct": None}
    best = min(rated, key=lambda m: m["loss12mPct"])
    worst = max(rated, key=lambda m: m["loss12mPct"])
    return {
        "best": {
            "model": best["model"],
            "storageLabel": best["storageLabel"],
            "loss12mPct": best["loss12mPct"],
        },
        "worst": {
            "model": worst["model"],
            "storageLabel": worst["storageLabel"],
            "loss12mPct": worst["loss12mPct"],
        },
        "avgLoss12mPct": round(
            sum(m["loss12mPct"] for m in rated) / len(rated), 1
        ),
    }


def get_depreciation(
    category: str = "smartphone",
    client: "Client | None" = None,
) -> dict[str, Any]:
    """Curva di deprezzamento per variante + confronto fra modelli.

    Sorgente: gli annunci ATTIVI e SANI, già raggruppati per variante canonica e
    ripuliti con IQR dal layer di valutazione — nessuna raccolta aggiuntiva.
    """
    from backend.core.database import get_db
    from backend.services.reads import _opportunities_table, _variant_price_pools

    db = client or get_db()
    table = _opportunities_table(category)

    # Solo tech: le auto hanno varianti per generazione, non per età del modello.
    if category == "automobile":
        return {
            "supported": False,
            "curves": [],
            "models": [],
            "storages": [],
            "summary": {"best": None, "worst": None, "avgLoss12mPct": None},
        }

    pools = _variant_price_pools(db, table)
    built = build_curves(pools)
    storages = sorted(
        {c["storage"] for c in built["curves"] if c["storage"] is not None}
    )
    return {
        "supported": True,
        "asOf": date.today().isoformat(),
        "storages": storages,
        "curves": built["curves"],
        "models": built["models"],
        "summary": _summary(built["models"]),
    }
