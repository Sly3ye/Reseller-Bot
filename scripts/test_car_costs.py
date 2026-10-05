"""Test dei costi d'acquisto auto (passaggio di proprietà), zero DB.

Esegui dalla root:  python scripts/test_car_costs.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import car_costs as cc  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("IPT (D.M. 435/1998, +30% provinciale massimo):")
ck("fino a 53 kW: 150,81 senza maggiorazione", cc.ipt_eur(50, 0), 150.81)
ck("53 kW: ancora la tariffa fissa", cc.ipt_eur(53, 0), 150.81)
ck("150 kW: 3,5119 x 150 (526,785)", cc.ipt_eur(150, 0), 526.78)
ck("150 kW con +30%", cc.ipt_eur(150, 30), 684.82)
ck("maggiorazione oltre il 30% non ammessa", cc.ipt_eur(150, 50), 684.82)
ck("kW ignoti = nessuna cifra", cc.ipt_eur(None), None)

print("Totale:")
cc.configure({"car_ipt_province_pct": 30, "car_agency_eur": 0, "car_prep_eur": 0, "car_dealer": False})
c = cc.acquisition_costs(150)
ck("voci fisse (27 + 10,20 + 64)", c["fees"], 101.2)
ck("passaggio 150 kW", c["transfer"], 786.02)
cc.configure({"car_agency_eur": 80, "car_prep_eur": 150})
ck("con agenzia e preparazione", cc.acquisition_costs(150)["total"], 1016.02)
cc.configure({"car_dealer": True})
ck("commerciante: emolumento 13,50", cc.acquisition_costs(150)["fees"], 87.7)
ck("kW ignoti: totale assente", cc.acquisition_costs(None)["total"], None)

print("Potenza dal testo:")
ck("218cv -> 160 kW", cc.kw_from_text("Bmw 125i 218cv 3p"), 160)
ck("150 kW", cc.kw_from_text("motore 150 kW / 204 Cv"), 150)
ck("nessuna potenza", cc.kw_from_text("BMW 123d"), None)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
