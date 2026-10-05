"""Matrice "dove cacciare" delle auto (punto 2 del verticale auto).

Per ogni modello@generazione con un modello di prezzo affidabile:
- quante auto attive, quante ne escono e ne spariscono a settimana;
- prezzo tipico;
- quante sono AFFARI: margine netto dopo i costi d'acquisto (passaggio &
  co., services/car_costs.py) sopra la soglia e sopra l'errore tipico della
  stima — uno scarto dentro l'errore è rumore, non un affare;
- margine tipico degli affari e potenziale €/settimana (affari nuovi a
  settimana × margine tipico): dove conviene passare il tempo.

Valuta tutte le auto con il solo modello di prezzo (niente arricchimento
completo dell'annuncio): su mezzo milione di righe resta nell'ordine dei
secondi, ed è in cache _CACHE_TTL_S.
"""

from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone
from typing import Any

TABLE = "live_opportunities_auto"
WINDOW_DAYS = 28
MIN_DEAL_MARGIN_EUR = 500     # sotto, il flip non vale il tempo (passaggio già scalato)
_CACHE_TTL_S = 3600
_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        ts = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return ts if ts.tzinfo else ts.replace(tzinfo=timezone.utc)


def get_car_hunt(force: bool = False, min_margin_eur: int = MIN_DEAL_MARGIN_EUR) -> dict[str, Any]:
    hit = _cache.get("auto")
    if hit and not force and time.monotonic() - hit[0] < _CACHE_TTL_S:
        return hit[1]
    result = _compute(min_margin_eur)
    _cache["auto"] = (time.monotonic(), result)
    return result


def _compute(min_margin_eur: int) -> dict[str, Any]:
    from backend.core.database import _get_pool, get_db  # noqa: PLC0415
    from backend.services import car_costs  # noqa: PLC0415
    from backend.services.reads import (  # noqa: PLC0415
        _car_model_name, _car_price_models, _cols, _model_key, _variant_median_kw, car_attributes,
    )
    from backend.services.valuation import car_expected_price  # noqa: PLC0415
    from backend.services.variants import (  # noqa: PLC0415
        CAR_GEN_SEP, car_generation_label, is_healthy, year_fits_generation,
    )

    db = get_db()
    models = _car_price_models(db, TABLE)
    variant_kw = _variant_median_kw(db, TABLE)
    cutoff = datetime.now(timezone.utc) - timedelta(days=WINDOW_DAYS)
    cols = _cols(TABLE, "variant_key", "year", "km", "asking_price", "condition_tier", "title",
                 "power_kw", "body_type", "fuel", "transmission", "found_at", "status",
                 "updated_at", "car_brand")
    with _get_pool().connection() as conn:
        rows = conn.execute(
            f"select {cols} from public.{TABLE} where variant_key like %s and "
            f"(status in ('nuovo','visto') or (status = 'venduto_rimosso' and updated_at >= %s))",
            (f"%{CAR_GEN_SEP}%", cutoff),
        ).fetchall()

    cells: dict[str, dict[str, Any]] = {}
    for r in rows:
        vk = r["variant_key"]
        if vk.endswith(("@nd", "@escluso")):
            continue
        c = cells.setdefault(vk, {"active": 0, "new": 0, "gone": 0, "prices": [], "deals": [],
                                  "newDeals": 0, "brand": r.get("car_brand")})
        if r["status"] == "venduto_rimosso":
            c["gone"] += 1
            continue
        c["active"] += 1
        price = float(r["asking_price"] or 0)
        if price > 0:
            c["prices"].append(price)
        found = _parse_ts(r.get("found_at"))
        if found and found >= cutoff:
            c["new"] += 1
        model = models.get(vk)
        if not model or not is_healthy(r.get("condition_tier") or "buono") or price <= 0:
            continue
        if not year_fits_generation(vk, r.get("year")):
            continue
        expected = car_expected_price(model, r.get("year"), r.get("km"), car_attributes(r))
        if not expected:
            continue
        kw = r.get("power_kw") or car_costs.kw_from_text(r.get("title")) or variant_kw.get(vk)
        costs = car_costs.acquisition_costs(kw)["total"]
        if costs is None:
            continue
        net = expected - price - costs
        # Affare = margine netto sopra la soglia E sopra l'errore tipico della stima.
        if net >= max(min_margin_eur, expected * model["errPct"] / 100):
            c["deals"].append(net)
            if found and found >= cutoff:
                c["newDeals"] += 1

    weeks = WINDOW_DAYS / 7
    out = []
    for vk, c in cells.items():
        model = models.get(vk)
        mk = _model_key(vk)
        deals = c["deals"]
        typical = round(statistics.median(deals)) if deals else None
        out.append({
            "variantKey": vk,
            "label": f"{_car_model_name(mk, c['brand'])} {car_generation_label(vk)}",
            "modelKey": mk,
            "active": c["active"],
            "newPerWeek": round(c["new"] / weeks, 1),
            "gonePerWeek": round(c["gone"] / weeks, 1),
            "medianPrice": round(statistics.median(c["prices"])) if c["prices"] else None,
            "valued": model is not None,
            "modelSamples": model["n"] if model else None,
            "errPct": model["errPct"] if model else None,
            "modelLevel": model.get("level") if model else None,
            "deals": len(deals),
            "typicalDealMargin": typical,
            "dealsPerWeek": round(c["newDeals"] / weeks, 1),
            "weeklyPotentialEur": round(c["newDeals"] / weeks * typical) if typical else None,
        })
    out.sort(key=lambda x: (x["weeklyPotentialEur"] is None, -(x["weeklyPotentialEur"] or 0),
                            -x["active"]))
    return {
        "cells": out,
        "windowDays": WINDOW_DAYS,
        "minDealMarginEur": min_margin_eur,
        "valuedVariants": sum(1 for x in out if x["valued"]),
        "totalVariants": len(out),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "note": ("gonePerWeek conta le auto sparite negli inventari a rotazione: è affidabile "
                 "solo dopo il primo ciclo completo."),
    }
