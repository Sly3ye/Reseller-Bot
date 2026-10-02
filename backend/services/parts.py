"""Costi dei ricambi per modello: due colonne, ORIGINALE Apple e AFTERMARKET.

Fonti (file versionati in ``backend/data/``, si aggiornano con gli script):
- ``apple_parts_it.json``  ← ``scripts/fetch_apple_parts.py`` (Self Service
  Repair Store Italia, IVA inclusa, con il CREDITO che Apple rimborsa se le
  rispedisci la parte vecchia: per la batteria circa metà del prezzo);
- ``aftermarket_parts_it.json`` ← ``scripts/fetch_aftermarket_parts.py``
  (catalogo di un rivenditore italiano di ricambi per laboratori).

Il calcolo margini usa la colonna scelta nelle Impostazioni (``repair_source``,
default aftermarket: è come ripari davvero) più la manodopera per tipo di
intervento (``repair_labor_eur``, default 0: lo fai tu). Se un modello non ha
il ricambio nella colonna scelta si ripiega sull'altra, e infine sulla
vecchia tabella Apple per fascia (``scoring.APPLE_PART_EUR``).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[1] / "data"

# Difetto (NLP) → ricambio. La scocca (vetro posteriore) solo aftermarket:
# Apple non la vende come ricambio self-service.
DEFECT_TO_PART = {
    "schermo-rotto": "schermo",
    "batteria-esausta": "batteria",
    "back-rotto": "scocca",
}
PART_LABEL = {"schermo": "Schermo", "batteria": "Batteria", "scocca": "Scocca posteriore"}

# Impostazioni (sovrascritte da settings_store.apply → configure()).
CONFIG: dict[str, Any] = {
    "repair_source": "aftermarket",          # "aftermarket" | "apple"
    "apple_return_credit": True,             # rispedisci la parte vecchia ad Apple
    "repair_labor_eur": {"schermo": 0, "batteria": 0, "scocca": 0},
}


def configure(cfg: dict[str, Any]) -> None:
    for key in ("repair_source", "apple_return_credit"):
        if key in cfg:
            CONFIG[key] = cfg[key]
    labor = cfg.get("repair_labor_eur")
    if isinstance(labor, dict):
        for part, value in labor.items():
            try:
                CONFIG["repair_labor_eur"][part] = float(value)
            except (TypeError, ValueError):
                pass


@lru_cache(maxsize=None)
def _catalog(name: str) -> dict[str, Any]:
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8")).get("models", {})


def apple_cost(model_key: str | None, part: str) -> dict[str, Any] | None:
    """{price, credit, net} del ricambio originale, o None se Apple non lo vende."""
    entry = (_catalog("apple_parts_it.json").get(model_key or "") or {}).get(part)
    if not entry:
        return None
    credit = (entry.get("returnCreditEur") or 0) if CONFIG["apple_return_credit"] else 0
    return {
        "price": entry["priceEur"],
        "credit": credit,
        "net": round(entry["priceEur"] - credit, 2),
    }


def aftermarket_cost(model_key: str | None, part: str) -> dict[str, Any] | None:
    """{price, grade, name} del ricambio aftermarket consigliato, o None."""
    rec = ((_catalog("aftermarket_parts_it.json").get(model_key or "") or {}).get(part) or {}).get(
        "recommended"
    )
    if not rec:
        return None
    return {"price": rec["priceEur"], "grade": rec["grade"], "name": rec["name"]}


def part_quote(model_key: str | None, part: str) -> dict[str, Any]:
    """Le due colonne per un ricambio + il costo usato nei conti (colonna scelta,
    con ripiego sull'altra) comprensivo di manodopera."""
    apple = apple_cost(model_key, part)
    after = aftermarket_cost(model_key, part)
    preferred = CONFIG["repair_source"]
    chosen, used = None, None
    for source in ([preferred] + [s for s in ("aftermarket", "apple") if s != preferred]):
        if source == "apple" and apple:
            chosen, used = apple["net"], "apple"
            break
        if source == "aftermarket" and after:
            chosen, used = after["price"], "aftermarket"
            break
    labor = float(CONFIG["repair_labor_eur"].get(part, 0) or 0)
    return {
        "part": part,
        "label": PART_LABEL.get(part, part),
        "apple": apple,
        "aftermarket": after,
        "source": used,
        "labor": labor,
        "cost": round(chosen + labor, 2) if chosen is not None else None,
    }
