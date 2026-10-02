"""Test del feedback dalle riparazioni (E3), zero dipendenze DB.

Esegui dalla root:  python scripts/test_repair_feedback.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services import parts, repair_feedback as rf  # noqa: E402

_passed = 0
_failed = 0


def ck(desc, got, want):
    global _passed, _failed
    ok = got == want
    _passed += ok
    _failed += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


def deal(lid, est_cost, actual, outcome="riuscita", part="schermo", source="aftermarket"):
    return {
        "listing_id": lid,
        "estimate": {"repairItems": [{"part": part, "source": source, "cost": est_cost}]},
        "repair": {"parts": [{"part": part, "source": source, "cost": actual}], "outcome": outcome},
    }


print("Correzione ricambi:")
deals = [deal("a", 40, 44), deal("b", 50, 60), deal("c", 40, 46), deal("d", 40, 400)]
fb = rf.compute_feedback(deals)
sch = fb["parts"]["schermo:aftermarket"]
ck("errore di battitura (×10) scartato", sch["n"], 3)
ck("rapporto mediano", sch["ratio"], 1.15)
ck("applicato da 3", sch["applied"], True)
fb2 = rf.compute_feedback(deals[:2])
ck("2 casi: non applicato", fb2["parts"]["schermo:aftermarket"]["applied"], False)
ck("senza esito non conta", rf.compute_feedback([{**deals[0], "repair": {"parts": []}}])["repairs"], 0)
ck("partCost preferito a cost",
   rf.compute_feedback([{
       "listing_id": "x",
       "estimate": {"repairItems": [{"part": "batteria", "source": "aftermarket", "cost": 30, "partCost": 20}]},
       "repair": {"parts": [{"part": "batteria", "source": "aftermarket", "cost": 22}], "outcome": "riuscita"},
   }])["parts"]["batteria:aftermarket"]["ratio"], 1.1)

print("Riuscita per guasto:")
g = {"a": ["non-si-accende"], "b": ["non-si-accende"], "c": ["non-si-accende", "schermo"], "d": ["schermo"]}
outs = [deal("a", 40, 40, "fallita"), deal("b", 40, 40, "riuscita"),
        deal("c", 40, 40, "parziale"), deal("d", 40, 40, "riuscita")]
fb = rf.compute_feedback(outs, g)
ck("non si accende 1/3", fb["guasti"]["non-si-accende"]["successPct"], 33.3)
ck("affidabile con 3", fb["guasti"]["non-si-accende"]["reliable"], True)
ck("schermo 2 casi: non affidabile", fb["guasti"]["schermo"]["reliable"], False)

print("Applicazione al preventivo:")
rf.STATE.update(rf.compute_feedback(deals))
model = next(iter(parts._catalog("aftermarket_parts_it.json")), None)
q = parts.part_quote(model, "schermo")
if q["listCost"] is not None and q["source"] == "aftermarket":
    ck("costo corretto ×1.15", q["partCost"], round(q["listCost"] * 1.15, 2))
    ck("correzione dichiarata", q["correction"], {"ratio": 1.15, "n": 3})
rf.STATE.update({"parts": {}, "guasti": {}, "repairs": 0})
q = parts.part_quote(model, "schermo")
ck("senza riparazioni = listino", q["partCost"], q["listCost"])
rf.STATE.update(rf.compute_feedback(outs, g))
ck("track record prudente", rf.guasto_success(["schermo", "non-si-accende"])["guasto"], "non-si-accende")

print(f"\n=== {_passed} PASS / {_failed} FAIL ===")
raise SystemExit(1 if _failed else 0)
