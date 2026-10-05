"""Test dei criteri degli alert auto, zero DB.

Esegui dalla root:  python scripts/test_car_alerts.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.car_alerts import matches, select_car_alerts  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


car = {"netMarginAfterCostsEur": 1500, "carModel": {"n": 30}, "risk": None, "conditionTier": "buono",
       "askingPrice": 9000, "variantKey": "alfa-romeo-giulietta@tutte", "location": "Milano (MI)"}
cfg = {"car_alert_min_net_margin_eur": 800, "car_alert_max_price": 0, "car_alert_brands": [], "car_alert_zones": []}
print("Alert auto:")
ck("affare base", matches(car, cfg), True)
ck("margine sotto soglia", matches({**car, "netMarginAfterCostsEur": 500}, cfg), False)
ck("senza modello di prezzo", matches({**car, "carModel": None}, cfg), False)
ck("rischio alto", matches({**car, "risk": {"level": "alto"}}, cfg), False)
ck("incidentata", matches({**car, "conditionTier": "incidentata"}, cfg), False)
ck("oltre il budget", matches(car, {**cfg, "car_alert_max_price": 8000}), False)
ck("marca con spazio ('Alfa Romeo')", matches(car, {**cfg, "car_alert_brands": ["Alfa Romeo"]}), True)
ck("marca diversa", matches(car, {**cfg, "car_alert_brands": ["BMW"]}), False)
ck("zona per provincia", matches(car, {**cfg, "car_alert_zones": ["milano"]}), True)
ck("zona fuori", matches(car, {**cfg, "car_alert_zones": ["Roma"]}), False)
ck("ordine per margine", [c["netMarginAfterCostsEur"] for c in select_car_alerts(
    [car, {**car, "netMarginAfterCostsEur": 3000}], cfg)], [3000, 1500])

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
