"""Test offline del riconoscimento ripubblicazioni senza foto (services/republish).

Esegui dalla root:  python scripts/test_republish.py
"""

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.republish import match_pairs, merge_into_old  # noqa: E402

PASS = FAIL = 0


def ck(desc, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


def ad(i, seller="s1", vk="iphone-13-128", price=400, title="iPhone 13 128GB", **kw):
    return {"id": i, "seller_id": seller, "variant_key": vk, "price": price, "title": title, **kw}


always = lambda new, old: True  # noqa: E731

print("match_pairs")
ck("stesso venditore/variante/prezzo vicino",
   [(n["id"], o["id"]) for n, o in match_pairs("smartphone", [ad("n")], [ad("o", price=420)], always)],
   [("n", "o")])
ck("prezzo oltre ±15% → no", match_pairs("smartphone", [ad("n")], [ad("o", price=520)], always), [])
ck("venditore diverso → no", match_pairs("smartphone", [ad("n")], [ad("o", seller="s2")], always), [])
ck("variante diversa → no", match_pairs("smartphone", [ad("n")], [ad("o", vk="iphone-13-256")], always), [])
ck("titolo senza modello (tech) → no",
   match_pairs("smartphone", [ad("n", title="telefono usato")], [ad("o", title="telefono usato")], always), [])
ck("senza venditore → no", match_pairs("smartphone", [ad("n", seller=None)], [ad("o", seller=None)], always), [])
ck("ogni vecchio usato una volta",
   len(match_pairs("smartphone", [ad("n1"), ad("n2")], [ad("o")], always)), 1)
ck("sceglie il prezzo più vicino",
   [o["id"] for _, o in match_pairs("smartphone", [ad("n", price=400)],
                                    [ad("o1", price=440), ad("o2", price=405)], always)],
   ["o2"])
ck("auto: basta venditore+variante",
   len(match_pairs("automobile", [ad("n", vk="bmw-123d", title="BMW")],
                   [ad("o", vk="bmw-123d", title="BMW")], always)), 1)

print("merge_into_old (regola temporale)")
now = datetime.now(timezone.utc)


class FakeDB:
    def __init__(self): self.ops = []
    def table(self, name): self._t = name; return self
    def update(self, patch): self.ops.append(("update", self._t, patch)); return self
    def delete(self): self.ops.append(("delete", self._t)); return self
    def eq(self, *a): return self
    def execute(self): return self


old = {"id": "o", "listing_url": "u-old", "seller_id": "s1", "variant_key": "iphone-13-128",
       "title": "iPhone 13 128GB", "asking_price": 400,
       "updated_at": (now - timedelta(days=1)).isoformat()}
twin_new = {"id": "n", "listing_url": "u-new", "seller_id": "s1", "variant_key": "iphone-13-128",
            "title": "iPhone 13 128GB", "asking_price": 390,
            "published_at": now.isoformat(), "found_at": now.isoformat()}
twin_vecchio = {**twin_new, "published_at": (now - timedelta(days=40)).isoformat()}

db = FakeDB()
ck("gemello nato dopo la sparizione → fuso", merge_into_old(db, "t", "smartphone", [old], [twin_new]), ["o"])
ck("ordine prudente: prima URL temporaneo, delete per ultimo",
   [op[0] for op in db.ops], ["update", "update", "update", "update", "delete"])
ck("secondo pezzo online da 40 giorni (negozio) → non fuso",
   merge_into_old(FakeDB(), "t", "smartphone", [old], [twin_vecchio]), [])

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
