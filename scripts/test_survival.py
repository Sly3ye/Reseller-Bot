"""Test offline di Kaplan–Meier e della natura delle sparizioni (services/survival).

Esegui dalla root:  python scripts/test_survival.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.survival import (  # noqa: E402
    kaplan_meier, km_median, km_sold_by, removal_kind, survival_summary,
)

PASS = FAIL = 0


def ck(desc, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


print("kaplan_meier")
# Tutti venduti: la mediana KM coincide con quella empirica.
obs = [(d, True) for d in (2, 4, 6, 8, 10)]
ck("senza censure, mediana = 6", km_median(kaplan_meier(obs)), 6)
# Esempio da manuale: 6 soggetti, censure a 3 e 5.
curve = kaplan_meier([(1, True), (2, True), (3, False), (4, True), (5, False), (6, True)])
ck("curva da manuale", [(t, round(s, 4)) for t, s in curve],
   [(1, 0.8333), (2, 0.6667), (4, 0.4444), (6, 0.0)])
ck("mediana da manuale = 4", km_median(curve), 4)
# Il punto della proposta: i venduti veloci + tanti invenduti ancora online.
fast_sold = [(d, True) for d in (1, 2, 3)]
still_online = [(60, False)] * 7
naive = sum(d for d, _ in fast_sold) / len(fast_sold)
km = km_median(kaplan_meier(fast_sold + still_online))
ck("media dei soli venduti = 2 giorni (ottimista)", naive, 2.0)
ck("KM: metà non si vende in finestra → None", km, None)
ck("KM: venduto entro 7gg = 30%", round(km_sold_by(kaplan_meier(fast_sold + still_online), 7), 2), 0.3)
s = survival_summary(fast_sold + still_online)
ck("sintesi: eventi/censurati", (s["events"], s["censored"]), (3, 7))
ck("nessuna osservazione", survival_summary([])["medianDays"], None)

print("entrata ritardata (stock trovato gia' vecchio)")
# 10 annunci nuovi: 5 venduti al giorno 10. 10 annunci trovati gia' a 100
# giorni di eta' e ancora online a 120: non devono "allungare" il giorno 10.
new_ones = [(10, True)] * 5 + [(30, False)] * 5
old_stock = [(120, False, 100)] * 10
ck("senza entrata: il vecchio stock diluisce", round(km_sold_by(kaplan_meier(new_ones + [(120, False)] * 10), 10), 2), 0.25)
ck("con entrata: solo chi era a rischio al giorno 10", round(km_sold_by(kaplan_meier(new_ones + old_stock), 10), 2), 0.5)
ck("entrata oltre l'uscita viene limitata", kaplan_meier([(5, True, 9)]), [(5.0, 0.0)])

print("removal_kind")
ck("sparito giovane → venduto", removal_kind(5, False, 400, 380), "venduto")
ck("oltre 2 anni → scaduto", removal_kind(740, True, 300, 380), "scaduto")
ck("14 mesi, ha ribassato → venduto (Subito non scade a 1 anno)", removal_kind(420, True, 300, 380), "venduto")
ck("4 mesi, mai ribassato, +20% sul mercato → ritirato", removal_kind(120, False, 460, 380), "ritirato")
ck("4 mesi ma ha ribassato → venduto", removal_kind(120, True, 460, 380), "venduto")
ck("4 mesi, prezzo in linea → venduto", removal_kind(120, False, 390, 380), "venduto")
ck("senza mediana di mercato → venduto", removal_kind(120, False, 460, None), "venduto")

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
