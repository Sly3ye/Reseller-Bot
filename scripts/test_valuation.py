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

print("AUTO (modello eta + km per generazione):")
import random as _r
_r.seed(7)
# Mercato sintetico: 20.000 EUR nuova, -10%/anno, -5% ogni 10.000 km, rumore +-6%.
rows = []
for _ in range(40):
    year, km = _r.randint(2012, 2019), _r.randint(30000, 200000)
    price = 20000 * 0.9 ** (2026 - year) * 0.95 ** (km / 10000) * _r.uniform(0.94, 1.06)
    rows.append((year, km, price))
rows.append((2016, 90000, 900000))   # errore di battitura: deve uscire come anomalo
m = val.fit_car_price_model(rows, ref_year=2026)
ck("modello accettato", m is not None, True)
ck("anomalo scartato", m["n"], 40)
ck("-10%/anno ritrovato", round(m["perYearPct"]), -10)
ck("-5%/10.000 km ritrovato", round(m["per10kKmPct"]), -5)
exp = val.car_expected_price(m, 2016, 100000)
ck("prezzo atteso 2016/100k (~4.150)", abs(exp - 20000 * 0.9 ** 10 * 0.95 ** 10) / exp < 0.06, True)
ck("niente estrapolazione (2007)", val.car_expected_price(m, 2007, 100000), None)
ck("niente estrapolazione (400k km)", val.car_expected_price(m, 2016, 400000), None)
ck("pochi dati = nessun modello", val.fit_car_price_model(rows[:8], ref_year=2026), None)
ck("prezzo che SALE con i km = nessun modello",
   val.fit_car_price_model([(2015, km, 5000 + km / 10) for km in range(20000, 200000, 12000)], ref_year=2026), None)
ev = val.evaluate_value(category="automobile", asking=round(exp * 0.7), condition_tier="buono",
                        variant_prices=[], km=100000, year=2016, car_model=m)
ck("affare a -30%", ev["dealClass"], "affare")
ck("fonte eta-km", ev["fairValueSource"], "eta-km")
ck("errore tipico dichiarato", ev["fairValueErrPct"] is not None and ev["fairValueErrPct"] < 10, True)
ck("senza modello: niente valore equo (non la mediana)",
   val.evaluate_value(category="automobile", asking=5000, condition_tier="buono",
                      variant_prices=[9000, 9500, 10000], km=100000, year=2016)["fairValue"], None)
ck("incidentata abbassa", val.evaluate_value(category="automobile", asking=3000, condition_tier="incidentata",
   variant_prices=[], km=100000, year=2016, car_model=m)["fairValue"] < exp, True)

ck("km in migliaia (184 su un 2008)", val.normalize_km(184, 2008, 2026), 184000)
ck("km 0 vero su auto nuova", val.normalize_km(15, 2025, 2026), 15)

print("Edge:")
ck("pool<3 → n/d", val.evaluate_value(category="smartphone", asking=300, condition_tier="buono", variant_prices=[400, 450])["dealClass"], "n/d")

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
