"""Test della curva di deprezzamento (build_curves), zero dipendenze DB.

Esegui dalla root:  python scripts/test_depreciation.py
"""

import importlib.util
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "depreciation", ROOT / "backend/services/depreciation.py"
)
d = importlib.util.module_from_spec(spec)
sys.modules["depreciation"] = d
spec.loader.exec_module(d)

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


# --- parsing della variante -------------------------------------------------
ck("variante base", d._parse_variant("iphone-15-128"), (15, "", 128))
ck("variante pro max", d._parse_variant("iphone-13-pro-max-256"), (13, "pro-max", 256))
ck("variante mini", d._parse_variant("iphone-13-mini-128"), (13, "mini", 128))
ck("linea e", d._parse_variant("iphone-16e-128"), (16, "e", 128))
ck("memoria non dichiarata", d._parse_variant("iphone-14-na"), (14, "", None))
ck("non iPhone", d._parse_variant("bmw-123d-2007-2013"), None)

# --- date di uscita (regola 2008 + numero) ----------------------------------
ck("uscita 13", d._release_date(13, ""), date(2021, 9, 1))
ck("uscita 16", d._release_date(16, "pro"), date(2024, 9, 1))
ck("uscita 16e (febbraio)", d._release_date(16, "e"), date(2025, 2, 1))

# --- curva su dati sintetici ------------------------------------------------
# Tre generazioni della linea Pro 128GB: 900 → 600 → 450, viste a settembre 2026.
pools = {
    "iphone-16-pro-128": [880, 900, 920, 900],
    "iphone-15-pro-128": [590, 600, 610, 600],
    "iphone-14-pro-128": [440, 450, 460, 450],
    # Campione troppo piccolo: deve sparire dalla curva.
    "iphone-13-pro-128": [300, 310],
}
out = d.build_curves(pools, today=date(2026, 9, 1))
curve = next(c for c in out["curves"] if c["line"] == "pro" and c["storage"] == 128)
models = {p["model"]: p for p in curve["points"]}

ck("una curva per linea+memoria", len(out["curves"]), 2)  # 128GB + "tutte"
ck("campione sotto soglia escluso", "iPhone 13 Pro" in models, False)
ck("punti ordinati dal più recente", [p["model"] for p in curve["points"]],
   ["iPhone 16 Pro", "iPhone 15 Pro", "iPhone 14 Pro"])
ck("età del 16 Pro a set 2026", models["iPhone 16 Pro"]["ageYears"], 2.0)
ck("mediana", models["iPhone 16 Pro"]["median"], 900)
ck("perdita 12 mesi in €", models["iPhone 16 Pro"]["loss12mEur"], 300)
ck("perdita 12 mesi in %", models["iPhone 16 Pro"]["loss12mPct"], 33.3)
ck("costo di magazzino €/mese", models["iPhone 16 Pro"]["carryCostMonthEur"], 25)
ck("confronto con la generazione prima", models["iPhone 16 Pro"]["vsModel"], "iPhone 15 Pro")
ck("valore residuo del più recente", models["iPhone 16 Pro"]["retentionPct"], 100.0)
ck("valore residuo del 14 Pro", models["iPhone 14 Pro"]["retentionPct"], 50.0)
ck("la generazione più vecchia non ha perdita",
   models["iPhone 14 Pro"]["loss12mEur"], None)

# Una sola generazione non fa una curva.
solo = d.build_curves({"iphone-16-pro-128": [900, 900, 900]}, today=date(2026, 9, 1))
ck("linea con una sola generazione scartata", len(solo["curves"]), 0)

summary = d._summary(out["models"])
ck("peggiore della gamma", summary["worst"]["model"], "iPhone 16 Pro")
ck("migliore della gamma", summary["best"]["model"], "iPhone 15 Pro")

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
