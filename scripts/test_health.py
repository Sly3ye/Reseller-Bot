"""Test della logica di stato dello scraper (Fase 3), zero dipendenze DB.

Esegui dalla root:  python scripts/test_health.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health", ROOT / "backend/services/health.py")
h = importlib.util.module_from_spec(spec)
sys.modules["health"] = h
spec.loader.exec_module(h)

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


ck("tutto ok", h.compute_status(17, 17, 0, 300), "ok")
ck("qualche fallito → degraded", h.compute_status(17, 15, 2, 280), "degraded")
ck("tutti falliti → down", h.compute_status(17, 0, 17, 0), "down")
ck("ok ma zero annunci → down", h.compute_status(17, 17, 0, 0), "down")
ck("nessun target → idle", h.compute_status(0, 0, 0, 0), "idle")

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
