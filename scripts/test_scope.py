"""Test dell'ambito iPhone (dal 12 in su), dei filtri modello e della raccolta, zero DB.

Esegui dalla root:  python scripts/test_scope.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scrapers.base import ScrapedListing  # noqa: E402
from backend.services.reads import tech_model_in_scope  # noqa: E402
from backend.services.scope import classify  # noqa: E402
from backend.services.sweep import is_relevant  # noqa: E402
from backend.services.variants import in_iphone_scope, iphone_generation  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("Generazione e ambito:")
ck("13 Pro", (iphone_generation("iphone-13-pro"), in_iphone_scope("iphone-13-pro")), (13, True))
ck("12 mini dentro", in_iphone_scope("iphone-12-mini"), True)
ck("16e e Air dentro", (in_iphone_scope("iphone-16e"), in_iphone_scope("iphone-air")), (True, True))
ck("11 fuori", in_iphone_scope("iphone-11-pro-max"), False)
ck("XR, XS Max, X, SE fuori", [in_iphone_scope(k) for k in ("iphone-xr", "iphone-xs-max", "iphone-x", "iphone-se")],
   [False, False, False, False])
ck("modello non riconosciuto: non si sa", in_iphone_scope("iphone-pro-max"), None)

print("Filtro modelli del feed:")
ck("modello vero nell'ambito", tech_model_in_scope("iphone-15-pro"), True)
ck("modello vero fuori ambito", tech_model_in_scope("iphone-11"), False)
for junk in ("iphone-usati", "iphone-pro-max", "samsung-s26-ultra", "scatole-iphone", "iphone"):
    ck(f"voce spazzatura fuori: {junk}", tech_model_in_scope(junk), False)

print("Archivio:")
ck("11 Pro in archivio", classify("iphone-11-pro-128", "iPhone 11 Pro 128GB"), "sotto_ambito")
ck("SE in archivio", classify("iphone-se-64", "iPhone SE 2022 64GB"), "sotto_ambito")
ck("13 resta", classify("iphone-13-128", "iPhone 13 128GB"), None)
ck("modello non riconosciuto resta (lo legge l'AI)", classify("iphone-usati", "iPhone usati"), None)
ck("altro marchio in archivio", classify("samsung-s26-ultra", "Samsung S26 Ultra pari a iPhone"), "non_iphone")
ck("scatola in archivio", classify("scatole-iphone", "Scatole iPhone 15"), "non_iphone")

print("Raccolta:")


def rel(title, description=None):
    return is_relevant(ScrapedListing(source="subito", title=title, url="u", description=description), "smartphone")


ck("iPhone 15 si raccoglie", rel("iPhone 15 128GB"), True)
ck("iPhone 11 no", rel("iPhone 11 Pro 64GB"), False)
ck("iPhone XR no", rel("Iphone XR 64 gb"), False)
ck("modello non riconosciuto si raccoglie", rel("iPhone usato come nuovo"), True)
ck("modello nella descrizione: 8 no", rel("iPhone", "Vendo iPhone 8 64GB funzionante"), False)
ck("modello nella descrizione: 14 sì", rel("Telefono iPhone", "Vendo iPhone 14 Pro 256GB"), True)
ck("Samsung senza iPhone no", rel("Samsung Galaxy S24"), False)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
