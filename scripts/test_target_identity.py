"""Test offline dell'identità dei target (scripts/target_identity) e della flotta
voluta da seed_targets.py.

Esegui dalla root:  python scripts/test_target_identity.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.config import settings  # noqa: E402
from scripts.seed_targets import desired_targets  # noqa: E402
from scripts.target_identity import match_target, target_key  # noqa: E402

PASS = FAIL = 0


def ck(desc, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


def t(i, query, filters=None, active=True, category="automobile"):
    return {"id": i, "category": category, "query": query,
            "strict_filters": filters or {}, "is_active": active}


GEN1 = {"min_year": 2007, "max_year": 2013}
GEN2 = {"min_year": 2012, "max_year": 2019}
MAC = [
    t("125-g1", "BMW 125i", GEN1, active=False),
    t("125-g2", "BMW 125i", GEN2),
    t("123-g1", "BMW 123d", GEN1),
    t("ip13", "iPhone 13", category="smartphone"),
]

print("target_key")
ck("ordine delle chiavi irrilevante",
   target_key(t("a", "X", {"min_year": 1, "max_year": 2})) == target_key(t("b", "X", {"max_year": 2, "min_year": 1})),
   True)
ck("filtri come stringa JSON", target_key({"category": "c", "query": "q", "strict_filters": '{"b": 1, "a": 2}'}),
   ("c", "q", '{"a": 2, "b": 1}'))
ck("filtri None = vuoti", target_key({"category": "c", "query": "q", "strict_filters": None})[2], "{}")

print("match_target")
ck("identità completa", match_target(t("s", "BMW 125i", GEN1, active=True), MAC), "125-g1")
ck("senza filtri → l'unico attivo con quel nome", match_target(t("s", "BMW 125i"), MAC), "125-g2")
ck("senza filtri, una sola generazione", match_target(t("s", "BMW 123d"), MAC), "123-g1")
ck("altra generazione → nuovo target", match_target(t("s", "BMW 123d", GEN2), MAC), None)
ck("nome sconosciuto → nuovo target", match_target(t("s", "Golf GTI"), MAC), None)
ck("iPhone (filtri vuoti)", match_target(t("s", "iPhone 13", category="smartphone"), MAC), "ip13")
ck("stesso nome, altra categoria → no", match_target(t("s", "iPhone 13"), MAC), None)
two_active = [t("a", "BMW 125i", GEN1), t("b", "BMW 125i", GEN2)]
ck("due attivi con quel nome → primo, deterministico", match_target(t("s", "BMW 125i"), two_active), "a")

print("seed_targets")
fleet = desired_targets()
keys = [target_key(x) for x in fleet]
ck("nessuna identità duplicata", len(keys), len(set(keys)))
cars = {x["query"]: x["strict_filters"] for x in fleet if x["category"] == "automobile"}
ck("BMW con la loro generazione", cars, {"BMW 123d": GEN1, "BMW 125i": GEN2})
below = f"iPhone {settings.iphone_min_gen - 1}"
ck(f"iPhone dalla gen {settings.iphone_min_gen} (IPHONE_MIN_GEN), filtri vuoti",
   all(x["strict_filters"] == {} for x in fleet if x["category"] == "smartphone")
   and not any(x["query"] == below for x in fleet), True)

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
