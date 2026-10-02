"""Test del resolver delle varianti canoniche (Fase 1 BI), zero dipendenze DB.

Carica variants.py per path così gira senza psycopg installato.
Esegui dalla root:  python scripts/test_variants.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # model_text importa nlp_parser (senza DB)
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
# Air (gen 17): senza suffisso dedicato finirebbe nel pool del 17 base, che vale
# ~200€ di più — media di mercato e valore equo falsati.
ck("17 Air 256", tech("iPhone 17 Air 256GB nero", 256)["variant_key"], "iphone-air-256")
ck("Air senza numero", tech("Iphone Air 256gb", 256)["variant_key"], "iphone-air-256")
ck("refuso I phone", tech("I phone 16 pro", 128)["variant_key"], "iphone-16-pro-128")
ck("refuso Iphome", tech("Iphome 17 pro", None)["variant_key"], "iphone-17-pro-na")
ck("XS Max", tech("iPhone XS Max 256GB", 256)["variant_key"], "iphone-xs-max-256")
ck("SE", tech("iPhone SE 2020 64gb", 64)["variant_key"], "iphone-se-64")
ck("8 Plus a una cifra", tech("iPhone 8 Plus", 64)["variant_key"], "iphone-8-plus-64")
ck("6s", tech("iPhone 6s 16GB", 16)["variant_key"], "iphone-6s-16")
ck("128gb non e' un 12", tech("vendo iphone 128gb", 128)["variant_key"] != "iphone-12-128", True)
ck("'12 e cover' non e' un 12e", tech("iPhone 12 e cover", 64)["variant_key"], "iphone-12-64")
ck("17 mini non esiste", v.iphone_model_key("iPhone 17 mini 128gb"), None)
ck("27 Pro Max e' un refuso", v.iphone_model_key("iPhone 27 Pro Max"), None)
ck("5c esiste", tech("iPhone 5c", 16)["variant_key"], "iphone-5c-16")
ck("'16 e' staccato = 16e", v.iphone_model_key("IPhone 16 e"), "iphone-16e")
ck("'16 e 128g' = 16e", v.iphone_model_key("iPhone 16 e 128g"), "iphone-16e")
ck("'16 e custodia' = 16", v.iphone_model_key("iPhone 16 e custodia"), "iphone-16")
ck("'XS Pro Max' = XS Max", v.iphone_model_key("Iphone xs pro max - 256 GB"), "iphone-xs-max")
ck("'5 SE' = SE", v.iphone_model_key("Iphone 5 SE 32GB"), "iphone-se")
ck("'5c 8 gb' non e' un 8", v.iphone_model_key("Apple iphone 5c 8 gb blu"), "iphone-5c")
ck("primo modello vince", tech("iPhone XR come iPhone 11", 64)["variant_key"], "iphone-xr-64")
ck("17 base ≠ Air", tech("iPhone 17 White 256GB", 256)["variant_key"], "iphone-17-256")
ck("storage n/d", tech("iPhone 14 Pro")["variant_key"], "iphone-14-pro-na")

print("TECH — modello dalla descrizione se il titolo tace:")
ck("titolo solo iphone", v.model_text("Iphone", "Vendo iphone 12 pro 256gb"), "iPhone 12 Pro")
ck("titolo con modello vince", v.model_text("iPhone 13", "come il mio vecchio iPhone 11"), "iPhone 13")
ck("due modelli = nessuno", v.model_text("Iphone", "passaggio ad iPhone 17, vendo iPhone 13"), "Iphone")
ck("stesso modello due volte", v.model_text("iPhone", "iPhone XR nero. Vendo iphone xr"), "iPhone XR")
ck("accessorio resta sul titolo", v.model_text("Cover per iPhone", "per iPhone 15 Pro"), "Cover per iPhone")
ck("variante dalla descrizione",
   v.resolve_variant("smartphone", "Iphone", {"storage_gb": 64}, description="Vendo iPhone 11 64gb")["variant_key"],
   "iphone-11-64")

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
