"""Test della coda delle verifiche dei venduti (a pezzi, ripresa dopo blocchi), zero DB e rete.

Esegui dalla root:  python scripts/test_verify_queue.py
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.services.garbage_collector as gc  # noqa: E402
import backend.services.sweep as sweep  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


store: dict[str, dict] = {}
marked: list[str] = []
calls: list[int] = []
sweep._load_state = lambda db, key: dict(store.get(key) or {})
sweep._save_state = lambda db, key, value: store.__setitem__(key, dict(value))


def fake_mark(table, ids):
    marked.extend(ids)
    return len(ids)


sweep._mark_removed_ids = fake_mark


def checker(block_after=None):
    """check_pages finto: un annuncio su tre è sparito; dopo block_after pagine, blocco."""
    async def fake(rows, job="verifiche"):
        calls.append(len(rows))
        done = rows if block_after is None else rows[:block_after]
        results = {r["id"]: int(r["id"]) % 3 == 0 for r in done}
        return results, {"checked": len(results), "aborted": block_after is not None}
    return fake


def reset(n):
    store.clear()
    marked.clear()
    calls.clear()
    sweep.save_verify_queue(None, "smartphone", [{"id": str(i), "listing_url": f"u{i}"} for i in range(n)], "test")


print("Coda delle verifiche:")
reset(120)
gc.check_pages = checker()
out = asyncio.run(sweep._drain_verify_queue(None, "smartphone"))
ck("tutte verificate a pezzi da 50", calls, [50, 50, 20])
ck("conteggi", out, {"checked": 120, "removed": 40})
ck("i rimossi marcati", len(marked), 40)
ck("coda vuota alla fine", store["verify_queue:smartphone"]["items"], [])

reset(120)
gc.check_pages = checker(block_after=20)
out = asyncio.run(sweep._drain_verify_queue(None, "smartphone"))
ck("blocco: si ferma al primo pezzo", calls, [50])
ck("restano in coda le pagine non verificate", len(store["verify_queue:smartphone"]["items"]), 100)
ck("e le verificate non ci sono più", "0" in {it["id"] for it in store["verify_queue:smartphone"]["items"]}, False)
ck("i rimossi verificati restano marcati", len(marked), 7)

reset(0)
out = asyncio.run(sweep._drain_verify_queue(None, "smartphone"))
ck("coda vuota: nessuna pagina", (calls, out), ([], {"checked": 0, "removed": 0}))

reset(100)


async def pruned_meanwhile(rows, job="verifiche"):
    """Durante il pezzo qualcuno pota la coda (es. l'archivio dei fuori ambito)."""
    st = store["verify_queue:smartphone"]
    st["items"] = [it for it in st["items"] if not 50 <= int(it["id"]) < 80]
    return {r["id"]: False for r in rows}, {"checked": len(rows), "aborted": True}


gc.check_pages = pruned_meanwhile
asyncio.run(sweep._drain_verify_queue(None, "smartphone"))
left = [int(it["id"]) for it in store["verify_queue:smartphone"]["items"]]
ck("coda potata durante un pezzo: i potati non tornano", (len(left), any(50 <= i < 80 for i in left)), (20, False))

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
