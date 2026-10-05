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
# Un criterio del compratore serve sempre: qui il budget.
cfg = {"car_alert_min_net_margin_eur": 800, "car_alert_max_price": 20000, "car_alert_brands": [],
       "car_alert_zones": []}
print("Alert auto:")
ck("affare base", matches(car, cfg), True)
ck("nessun criterio del compratore: niente alert", matches(car, {**cfg, "car_alert_max_price": 0}), False)
noisy = {**car, "carModel": {"n": 30, "errPct": 25}, "expectedPrice": 10000}
ck("margine dentro l'errore del modello (1.500 < 25% di 10.000)", matches(noisy, cfg), False)
ck("margine oltre l'errore del modello", matches({**noisy, "netMarginAfterCostsEur": 3000}, cfg), True)
ck("soglia di rumore spenta (0)", matches(noisy, {**cfg, "car_alert_min_err_multiple": 0}), True)
ck("margine sotto soglia", matches({**car, "netMarginAfterCostsEur": 500}, cfg), False)
ck("senza modello di prezzo", matches({**car, "carModel": None}, cfg), False)
ck("rischio alto", matches({**car, "risk": {"level": "alto"}}, cfg), False)
ck("incidentata", matches({**car, "conditionTier": "incidentata"}, cfg), False)
ck("oltre il budget", matches(car, {**cfg, "car_alert_max_price": 8000}), False)
ck("marca con spazio ('Alfa Romeo')", matches(car, {**cfg, "car_alert_brands": ["Alfa Romeo"]}), True)
ck("marca diversa", matches(car, {**cfg, "car_alert_brands": ["BMW"]}), False)
ck("zona per provincia", matches(car, {**cfg, "car_alert_zones": ["milano"]}), True)
ck("zona fuori", matches(car, {**cfg, "car_alert_zones": ["Roma"]}), False)
ck("entro il raggio", matches({**car, "distanceKm": 30}, {**cfg, "car_alert_radius_km": 50}), True)
ck("fuori raggio", matches({**car, "distanceKm": 80}, {**cfg, "car_alert_radius_km": 50}), False)
ck("raggio senza distanza nota", matches(car, {**cfg, "car_alert_radius_km": 50}), False)
ck("ordine per margine", [c["netMarginAfterCostsEur"] for c in select_car_alerts(
    [car, {**car, "netMarginAfterCostsEur": 3000}], cfg)], [3000, 1500])

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
