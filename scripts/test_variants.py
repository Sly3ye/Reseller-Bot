"""Test del resolver delle varianti canoniche (Fase 1 BI), zero dipendenze DB.

Carica variants.py per path così gira senza psycopg installato.
Esegui dalla root:  python scripts/test_variants.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location(
    "variants", ROOT / "backend/services/variants.py"
)
v = importlib.util.module_from_spec(spec)
sys.modules["variants"] = v
spec.loader.exec_module(v)

_passed = 0
_failed = 0


def ck(desc, got, want):
    global _passed, _failed
    ok = got == want
    _passed += ok
    _failed += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


def tech(title, storage=None, defects=None, features=None):
    return v.resolve_variant(
        "smartphone", title,
        {"storage_gb": storage, "defects_noted": defects or [], "features": features or []},
    )


def auto(query, sf, defects=None):
    return v.resolve_variant(
        "automobile", (query or "") + " usata",
        {"defects_noted": defects or [], "features": []},
        query=query, strict_filters=sf,
    )


print("TECH — chiavi variante (scrematura base/Pro/memoria):")
ck("13 Pro Max 256", tech("iPhone 13 Pro Max 256GB", 256)["variant_key"], "iphone-13-pro-max-256")
ck("13 base 128", tech("iPhone 13 128GB", 128)["variant_key"], "iphone-13-128")
ck("13 Pro != 13 base",
   tech("iPhone 13 Pro 128GB", 128)["variant_key"] != tech("iPhone 13 128GB", 128)["variant_key"], True)
ck("15 Pro 1TB", tech("Apple iPhone 15 Pro 1TB", 1024)["variant_key"], "iphone-15-pro-1024")
ck("16e 128", tech("iPhone 16e 128GB", 128)["variant_key"], "iphone-16e-128")
ck("13 mini", tech("iPhone 13 mini 256", 256)["variant_key"], "iphone-13-mini-256")
ck("storage n/d", tech("iPhone 14 Pro")["variant_key"], "iphone-14-pro-na")

print("TECH — label & condizione:")
ck("label Pro Max", tech("iPhone 13 Pro Max 256GB", 256)["variant_label"], "iPhone 13 Pro Max 256GB")
ck("label 16e", tech("iPhone 16e 128GB", 128)["variant_label"], "iPhone 16e 128GB")
ck("mint", tech("iPhone 13 128GB", 128, features=["Pari-al-Nuovo"])["condition_tier"], "come-nuovo")
ck("rotto", tech("iPhone 13", 128, defects=["schermo-rotto"])["condition_tier"], "rotto")
ck("difetti", tech("iPhone 13", 128, defects=["batteria-esausta"])["condition_tier"], "difetti")
ck("buono", tech("iPhone 13", 128)["condition_tier"], "buono")

print("AUTO — variante per generazione (dal target):")
ck("123d gen", auto("BMW 123d", {"min_year": 2007, "max_year": 2013})["variant_key"], "bmw-123d-2007-2013")
ck("125i F20", auto("BMW 125i", {"min_year": 2012, "max_year": 2019})["variant_key"], "bmw-125i-2012-2019")
ck("no filtri", auto("BMW 123d", {})["variant_key"], "bmw-123d")
ck("incidentata", auto("BMW 123d", {}, defects=["incidentata"])["condition_tier"], "incidentata")

print("Helper is_healthy:")
ck("buono sano", v.is_healthy("buono"), True)
ck("rotto non sano", v.is_healthy("rotto"), False)

print(f"\n=== {_passed} PASS / {_failed} FAIL ===")
raise SystemExit(1 if _failed else 0)
