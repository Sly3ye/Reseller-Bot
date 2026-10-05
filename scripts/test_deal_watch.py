"""Test di emivita, deriva, riposizionamenti e segnali dell'annuncio, zero DB.

Esegui dalla root:  python scripts/test_deal_watch.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.deal_watch import half_life_stats  # noqa: E402
from backend.services.drift import evaluate  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("Emivita degli affari:")
# 10 affari vecchi di 2 giorni: 3 spariti entro 30', altri 3 entro 2 h, 4 ancora online.
old = ([{"ageMin": 2880, "goneMin": 20}] * 3 + [{"ageMin": 2880, "goneMin": 100}] * 3
       + [{"ageMin": 2880, "goneMin": None}] * 4)
s = half_life_stats(old)
ck("n e spariti", (s["n"], s["gone"]), (10, 6))
ck("quota entro 30'", s["withinPct"]["30"], 0.3)
ck("quota entro 2 h", s["withinPct"]["120"], 0.6)
ck("emivita = primo orizzonte con metà sparita", s["halfLifeMin"], 120)
# Affari di 5 minuti fa: non hanno avuto il tempo di sparire, non pesano sull'orizzonte di 15'.
fresh = [{"ageMin": 5, "goneMin": None}] * 20
s2 = half_life_stats(old + fresh)
ck("i freschi non abbassano la quota a 30'", s2["withinPct"]["30"], 0.3)
ck("campione troppo piccolo -> nessuna quota", half_life_stats(old[:4])["withinPct"]["15"], None)
ck("nessuno sparito -> emivita ignota", half_life_stats([{"ageMin": 600, "goneMin": None}] * 6)["halfLifeMin"],
   None)

print("Deriva del formato:")
base = {"potenza": 0.93, "foto": 0.99, "colore": 0.45, "provincia": 0.0}
ck("tutto normale", evaluate({"potenza": 0.90, "foto": 0.98, "colore": 0.10, "provincia": 0.0}, base), {})
ck("campo svuotato", list(evaluate({"potenza": 0.20, "foto": 0.98}, base)), ["potenza"])
ck("valori riportati", evaluate({"potenza": 0.2}, base)["potenza"], {"recent": 0.2, "base": 0.93})
ck("campo che di solito manca: niente allarme", evaluate({"colore": 0.0}, base), {})
ck("campo non misurato: ignorato", evaluate({}, base), {})

print("Riposizionamenti:")
from datetime import datetime, timezone  # noqa: E402

from backend.tasks import is_bump  # noqa: E402

first = datetime(2026, 10, 1, 8, 0, tzinfo=timezone.utc)
ck("data mostrata 4 giorni dopo = riposizionato", is_bump("2026-10-05T12:00:00+02:00", first) is not None, True)
ck("stessa ora in un altro fuso = niente", is_bump("2026-10-01T10:30:00+02:00", first), None)
ck("data senza fuso letta come UTC", is_bump("2026-10-01 08:00:00", "2026-10-01T08:00:00+00:00"), None)
ck("date mancanti o rotte = niente", (is_bump(None, first), is_bump("rotta", first)), (None, None))

print("Segnali dell'annuncio:")
from backend.services.reads import listing_signals  # noqa: E402

ck("nessun evento, annuncio fresco = niente", listing_signals(None, 3), None)
ck("fermo da 30 giorni senza ribassi", listing_signals({}, 30)["reasons"], ["online da 30 giorni senza ribassi"])
ck("fermo = livello medio", listing_signals({}, 30)["level"], "media")
s = listing_signals({"bumps30": 2, "drops": 1}, 40)
ck("riposizionato 2 volte = vuole vendere", (s["level"], s["reasons"][0]), ("alta", "riposizionato 2× in 30 giorni"))
ck("con un ribasso non si dice 'senza ribassi'", "online da 40 giorni senza ribassi" in s["reasons"], False)
ck("ripubblicato = alta", listing_signals({"relisted": 1}, 2)["level"], "alta")
ck("un ribasso solo non è un segnale (c'è già 'Già ribassato')", listing_signals({"drops": 1}, 5), None)
ck("due ribassi = tendenza", listing_signals({"drops": 2}, 5)["reasons"], ["ribassato 2×"])

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
