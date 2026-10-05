"""Market Intelligence auto: i modelli di prezzo per generazione e il
calcolatore "quanto vale?".

- ``car_models_overview``: per ogni generazione con un modello di prezzo,
  quanto pesano anno, km, potenza, carrozzeria, diesel, automatico, con
  campione ed errore tipico. È la curva di deprezzamento delle auto.
- ``car_value``: prezzo atteso di un'auto (generazione, anno, km, kW,
  carburante, cambio, carrozzeria) ± errore, costi d'acquisto e tetto: per
  valutare al volo un'auto vista ovunque, anche fuori da Subito.
"""

from __future__ import annotations

from typing import Any

TABLE = "live_opportunities_auto"


def _models() -> dict[str, dict[str, Any]]:
    """Modelli di prezzo dal contesto in cache del feed (15'), o calcolati."""
    import time  # noqa: PLC0415

    from backend.core.database import get_db  # noqa: PLC0415
    from backend.services import reads  # noqa: PLC0415

    hit = reads._ctx_cache.get(TABLE)
    if hit and time.monotonic() - hit[0] < reads._CTX_TTL_S and hit[1].get("car_models"):
        return hit[1]["car_models"]
    return reads._car_price_models(get_db(), TABLE)


def car_models_overview() -> dict[str, Any]:
    from backend.services.reads import _car_model_name, _model_key  # noqa: PLC0415
    from backend.services.variants import car_generation_label  # noqa: PLC0415

    models = _models()
    out = []
    for vk, m in models.items():
        out.append({
            "variantKey": vk,
            "label": f"{_car_model_name(_model_key(vk), None)} {car_generation_label(vk)}",
            "level": m.get("level"),
            "n": m["n"],
            "errPct": m["errPct"],
            "yearRange": m["yearRange"],
            "kmRange": m["kmRange"],
            "kwRange": m.get("kwRange"),
            "perYearPct": m.get("perYearPct"),
            "per10kKmPct": m.get("per10kKmPct"),
            "per10pctKwPct": m.get("per10pctKwPct"),
            "coupePct": m.get("coupePct"),
            "dieselPct": m.get("dieselPct"),
            "automaticPct": m.get("automaticPct"),
        })
    out.sort(key=lambda x: (x["level"] != "generazione", -x["n"]))
    return {"models": out, "count": len(out)}


def car_value(variant: str, year: int, km: int, kw: int | None = None, diesel: bool = False,
              automatic: bool = False, coupe: bool = False) -> dict[str, Any]:
    from backend.services import car_costs  # noqa: PLC0415
    from backend.services.scoring import max_bid  # noqa: PLC0415
    from backend.services.valuation import car_expected_price  # noqa: PLC0415

    model = _models().get(variant)
    if not model:
        return {"variantKey": variant, "expected": None,
                "reason": "nessun modello di prezzo per questa generazione (troppo poche auto)"}
    attrs = {"kw": kw, "diesel": diesel, "automatic": automatic, "coupe": coupe}
    expected = car_expected_price(model, year, km, attrs)
    if expected is None:
        return {"variantKey": variant, "expected": None,
                "reason": (f"fuori dal campione: anni {model['yearRange'][0]}–{model['yearRange'][1]}, "
                           f"km {model['kmRange'][0]:,}–{model['kmRange'][1]:,}".replace(",", ".")
                           + (f", kW {model['kwRange'][0]}–{model['kwRange'][1]}" if model.get("kwRange")
                              else ""))}
    err = model["errPct"] / 100
    carry = car_costs.carry_costs(expected, model.get("perYearPct"))
    costs = car_costs.acquisition_costs(kw, carry=carry)
    total = costs["total"] or 0
    return {
        "variantKey": variant,
        "expected": round(expected),
        "low": round(expected / (1 + err)),
        "high": round(expected * (1 + err)),
        "errPct": model["errPct"],
        "n": model["n"],
        "level": model.get("level"),
        "costs": costs,
        # Tetto per comprarla e rivenderla al prezzo atteso col margine obiettivo.
        "maxBid": max_bid("automobile", expected, 0, int(total), 0),
    }
