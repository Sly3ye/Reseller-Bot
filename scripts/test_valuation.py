"""Test della valutazione predittiva (Fase 2 BI), zero dipendenze DB.

Esegui dalla root:  python scripts/test_valuation.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "valuation", ROOT / "backend/services/valuation.py"
)
val = importlib.util.module_from_spec(spec)
sys.modules["valuation"] = val
spec.loader.exec_module(val)

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


PRICES = [400, 420, 450, 455, 460, 480, 500]  # mediana 455

print("TECH:")
ev = val.evaluate_value(category="smartphone", asking=350, condition_tier="buono", variant_prices=PRICES)
ck("fair = mediana", ev["fairValue"], 455.0)
ck("affare (350)", ev["dealClass"], "affare")
ck("posizione bassa", ev["pricePosition"] < 20, True)
ck("in-linea (460)", val.evaluate_value(category="smartphone", asking=460, condition_tier="buono", variant_prices=PRICES)["dealClass"], "in-linea")
ck("caro (600)", val.evaluate_value(category="smartphone", asking=600, condition_tier="buono", variant_prices=PRICES)["dealClass"], "caro")
ck("sospetto (150 no foto)", val.evaluate_value(category="smartphone", asking=150, condition_tier="buono", variant_prices=PRICES, has_images=False)["dealClass"], "sospetto")
ck("come-nuovo alza il fair", val.evaluate_value(category="smartphone", asking=455, condition_tier="come-nuovo", variant_prices=PRICES)["fairValue"] > 455, True)

print("AUTO (km-aware):")
km_model = (-0.08, 25000.0, 30)  # prezzo = 25000 - 0.08*km
ev = val.evaluate_value(category="automobile", asking=10000, condition_tier="buono", variant_prices=[12000, 13000, 14000, 15000], km=150000, km_model=km_model)
ck("fair da km (~13000)", ev["fairValue"], 13000.0)
ck("affare (10k vs 13k)", ev["dealClass"], "affare")
ck("incidentata abbassa", val.evaluate_value(category="automobile", asking=9000, condition_tier="incidentata", variant_prices=[12000, 13000, 14000, 15000], km=100000, km_model=km_model)["fairValue"] < 17000, True)

print("Edge:")
ck("pool<3 → n/d", val.evaluate_value(category="smartphone", asking=300, condition_tier="buono", variant_prices=[400, 450])["dealClass"], "n/d")

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
