"""Test del governatore del budget (priorità e pause del pacer), zero rete.

Esegui dalla root:  python scripts/test_governor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.scrapers.subito import HadesPacer, is_low_priority  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("Priorità:")
ck("testa alta", is_low_priority("testa_smartphone"), False)
ck("ricontrollo affari alto", is_low_priority("ricontrollo_affari"), False)
ck("sweep alto", is_low_priority("sweep_automobile"), False)
ck("cecchino alto", is_low_priority("cecchino"), False)
ck("inventario basso", is_low_priority("inventario_automobile"), True)
ck("verifiche basse", is_low_priority("verifiche"), True)
ck("senza etichetta basso", is_low_priority("altro"), True)

print("Pause dei lavori bassi:")
now = 100_000.0
p = HadesPacer()
ck("nessun errore: nessuna pausa", p.low_priority_hold(now), 0.0)
p._errors = [now - 50, now - 10]
ck("due errori: ancora niente", p.low_priority_hold(now), 0.0)
p._errors = [now - 100, now - 50, now - 10]
ck("tre errori in 10': pausa finché il terzo esce dalla finestra", p.low_priority_hold(now), 500.0)
p._errors = [now - 900, now - 800, now - 10]
ck("errori vecchi non contano", p.low_priority_hold(now), 0.0)
p._errors = []
p._blocked_until = now - 100
ck("15' dopo la fine di un blocco", p.low_priority_hold(now), 800.0)
p._blocked_until = now - 1000
ck("blocco finito da un pezzo", p.low_priority_hold(now), 0.0)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
