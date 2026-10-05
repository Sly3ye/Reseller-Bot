"""Test degli obiettivi della Goal Version (valutazione pura), zero DB.

Esegui dalla root:  python scripts/test_goals.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.goals import evaluate_goals  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


now = datetime(2026, 10, 5, 12, 0, tzinfo=timezone.utc)
dq = {
    "latency": {"alertP95Min": 1.4, "alerts7d": 30, "discoveryP50Min": 7},
    "alertDelivery7d": {"delivered": 25, "failed": 0, "not_sent": 5},
    "coverage": {"seenPct": 97.9, "inventoryAt": "2026-10-05T11:17:07+00:00"},
}
deal = {"stage": "venduto", "profit": 90.0, "estimatedMarginEur": 100.0,
        "updated_at": (now - timedelta(days=2)).isoformat()}
g = {x["key"]: x for x in evaluate_goals(dq, [deal], now)}
print("Obiettivi raggiunti:")
ck("latenza entro 2 min", (g["latenza"]["value"], g["latenza"]["ok"]), ("1.4 min", True))
ck("zero alert falliti", g["falliti"]["ok"], True)
ck("un affare chiuso questa settimana", (g["affari"]["value"], g["affari"]["ok"]), (1, True))
ck("copertura sopra il 95%", g["copertura"]["ok"], True)
ck("errore stima: 10% ma su 1 affare = non ancora giudicabile", (g["stima"]["value"], g["stima"]["ok"]), ("10%", None))

print("Non raggiunti o non misurabili:")
bad = {x["key"]: x for x in evaluate_goals(
    {"latency": {"alertP95Min": 6.0}, "alertDelivery7d": {"delivered": 3, "failed": 2},
     "coverage": {"seenPct": 80.0}},
    [{**deal, "updated_at": (now - timedelta(days=20)).isoformat()}], now)}
ck("latenza oltre", bad["latenza"]["ok"], False)
ck("alert falliti", (bad["falliti"]["value"], bad["falliti"]["ok"]), (2, False))
ck("nessun affare questa settimana", bad["affari"]["ok"], False)
ck("copertura bassa", bad["copertura"]["ok"], False)
empty = {x["key"]: x for x in evaluate_goals({}, [], now)}
ck("senza dati: latenza non misurabile", empty["latenza"]["ok"], None)
ck("senza invii: 'zero falliti' non si può dire", empty["falliti"]["ok"], None)
ck("senza inventario: copertura non misurabile", empty["copertura"]["ok"], None)
many = [{**deal, "profit": 95.0} for _ in range(30)]
ck("30 affari con errore 5%: raggiunto", {x["key"]: x for x in evaluate_goals(dq, many, now)}["stima"]["ok"], True)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
