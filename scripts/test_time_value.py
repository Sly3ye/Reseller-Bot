"""Test del profitto per ora di lavoro, zero DB.

Esegui dalla root:  python scripts/test_time_value.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.time_value import CONFIG, net_margin, profit_per_hour  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("Margine che conta:")
ck("rotto: netto post-riparazione", net_margin({"repair": {"netMarginEur": 90}, "marginVsFairEur": 300}, "smartphone"), 90.0)
ck("sano: valore equo meno magazzino", net_margin({"marginVsFairEur": 80, "carryCost": {"totalEur": 10}}, "smartphone"), 70.0)
ck("auto: netto dopo i costi", net_margin({"netMarginAfterCostsEur": 1500, "marginVsFairEur": 3000}, "automobile"), 1500.0)
ck("senza stima: niente", net_margin({}, "smartphone"), None)

print("Profitto per ora (tempi di default):")
near = profit_per_hour({"marginVsFairEur": 60, "distanceKm": 5}, "smartphone")
far = profit_per_hour({"marginVsFairEur": 90, "distanceKm": 80}, "smartphone")
ck("+60 € a 5 km batte +90 € a 80 km", near["eurPerHour"] > far["eurPerHour"], True)
ck("minuti di viaggio a 5 km (andata e ritorno a 50 km/h)", near["minutes"]["travel"], 12)
ck("ore = 12 + 20 + 45 minuti", near["hours"], round(77 / 60, 2))
rep = profit_per_hour({"repair": {"netMarginEur": 100, "items": [{"part": "schermo"}, {"part": "batteria"}]},
                       "distanceKm": 10}, "smartphone")
ck("riparazione = somma dei pezzi", rep["minutes"]["repair"], CONFIG["tv_repair_min"]["schermo"] + CONFIG["tv_repair_min"]["batteria"])
unk = profit_per_hour({"marginVsFairEur": 60}, "smartphone")
ck("senza distanza: ipotetica e dichiarata", (unk["distanceKnown"], unk["minutes"]["travel"]), (False, 60))
ck("auto: pratiche in più", profit_per_hour({"netMarginAfterCostsEur": 1000, "distanceKm": 20}, "automobile")["minutes"]["extra"], 240)

print("Probabilità solo se misurate:")
ck("senza emivita nessuna penalità", near["pAvailable"], None)
hl = profit_per_hour({"marginVsFairEur": 60, "distanceKm": 5}, "smartphone", half_life_min=36)
ck("emivita 36' e 36' per arrivare = metà", hl["pAvailable"], 0.5)
ck("valore atteso dimezzato", hl["expectedEur"], 30.0)
tr = profit_per_hour({"repair": {"netMarginEur": 100, "items": [{"part": "batteria"}]},
                      "repairTrackRecord": {"successPct": 80}, "distanceKm": 0}, "smartphone")
ck("le tue riparazioni riuscite all'80%", (tr["pRepair"], tr["expectedEur"]), (0.8, 80.0))
ck("nessuna stima del margine: niente", profit_per_hour({"distanceKm": 3}, "smartphone"), None)

print("Solo candidati credibili:")
ck("sospetto (accessorio, clone): niente", profit_per_hour({"marginVsFairEur": 1300, "dealClass": "sospetto"}, "smartphone"), None)
ck("valutazione da pochi campioni: niente", profit_per_hour({"marginVsFairEur": 900, "valuationConfidence": "bassa"}, "smartphone"), None)
ck("rischio alto: niente", profit_per_hour({"marginVsFairEur": 90, "risk": {"level": "alto"}}, "smartphone"), None)
ck("rischio medio: sì", profit_per_hour({"marginVsFairEur": 90, "risk": {"level": "medio"}}, "smartphone") is not None, True)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
