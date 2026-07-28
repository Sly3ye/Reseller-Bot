"""Test delle funzioni pure di intelligence (NLP + scoring), zero dipendenze DB.

Carica i moduli per path così girano anche senza psycopg/imagehash installati.
Esegui dalla root:  python scripts/test_intelligence.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nlp = _load("nlp_parser", "backend/scrapers/nlp_parser.py")
scoring = _load("scoring", "backend/services/scoring.py")

_passed = 0
_failed = 0


def check(desc, got, want):
    global _passed, _failed
    ok = got == want
    _passed += ok
    _failed += not ok
    mark = "OK  " if ok else "FAIL"
    extra = "" if ok else f"  (atteso {want})"
    print(f"  {mark} {desc}: {got}{extra}")


def test_nlp_tech():
    print("NLP tech:")
    r = nlp.parse_listing("iPhone 13 Pro 256GB", "batteria 89%, scatola e fattura")
    check("storage", r["storage_gb"], 256)
    check("batteria", r["battery_pct"], 89)
    check("corredo", set(r["features"]), {"Scatola", "Fattura"})
    r = nlp.parse_listing("iPhone 12 per ricambi", "schermo rotto e icloud bloccato")
    check("difetti", set(r["defects_noted"]), {"per-ricambi", "schermo-rotto", "icloud-bloccato"})
    check("exclude_iqr", r["exclude_from_iqr"], True)
    r = nlp.parse_listing("iPhone 15 Pro Max 1TB", "battery health 100%")
    check("storage_tb", r["storage_gb"], 1024)
    check("batteria_100", r["battery_pct"], 100)


def test_nlp_auto():
    print("NLP auto:")
    r = nlp.parse_listing("BMW 320d 2018 150.000 km", "M Sport, automatico, incidentata")
    check("km", r["km"], 150000)
    check("anno", r["year"], 2018)
    check("exclude_iqr", r["exclude_from_iqr"], True)


def test_scoring():
    print("Scoring:")
    ev = scoring.evaluate_opportunity(
        category="smartphone", title="iPhone 13 Pro Max", asking=300.0,
        market_avg=650.0, margin_pct=116.0, found_at="2026-07-17T11:00:00+00:00",
        seller_type="privato", defects=["schermo-rotto"], urgency=[],
        features=[], battery_pct=None, has_price_drop=False,
    )
    # Ricambi Apple per fascia (dalle Impostazioni): un Pro Max costa 380, non 300.
    check("repair_total", ev["repair"]["total"], 380)
    check("net_margin", ev["repair"]["netMarginEur"], -30.0)
    check("offer<asking", ev["suggestedOffer"] is not None and ev["suggestedOffer"] < 300, True)
    ev2 = scoring.evaluate_opportunity(
        category="automobile", title="Golf GTI", asking=17500.0, market_avg=21000.0,
        margin_pct=20.0, found_at="2026-07-15T10:00:00+00:00", seller_type="finto_privato",
        defects=["graffi", "grandine"], urgency=["realizzo"], features=[],
        battery_pct=None, has_price_drop=True,
    )
    check("penalty", ev2["defectPenaltyEur"], 1300)
    check("score_range", 0 <= ev2["score"] <= 100, True)
    check("offer_no_avg", scoring.suggested_offer("smartphone", None, 400), None)


def main() -> None:
    test_nlp_tech()
    test_nlp_auto()
    test_scoring()
    print(f"\n=== {_passed} PASS / {_failed} FAIL ===")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    main()
