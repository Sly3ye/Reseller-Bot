"""Test del bot Telegram (azioni sugli alert → pipeline), con un DB finto.

Esegui dalla root:  python scripts/test_telegram_bot.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backend.services.telegram_bot as bot  # noqa: E402

_p = _f = 0


def ck(desc, got, want):
    global _p, _f
    ok = got == want
    _p += ok
    _f += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


class Q:
    def __init__(self, db, table):
        self.db, self.table, self.filters, self.op, self.payload = db, table, [], "select", None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, *_a):
        return self

    def update(self, patch):
        self.op, self.payload = "update", patch
        return self

    def insert(self, row):
        self.op, self.payload = "insert", row
        return self

    def execute(self):
        rows = self.db.data.setdefault(self.table, [])
        match = [r for r in rows if all(str(r.get(c)) == str(v) for c, v in self.filters)]
        if self.op == "update":
            for r in match:
                r.update(self.payload)
        elif self.op == "insert":
            row = {"id": f"d{len(rows) + 1}", "stage": "interessante", **self.payload}
            rows.append(row)
            match = [row]
        return type("R", (), {"data": match})()


class FakeDB:
    def __init__(self):
        self.data = {"live_opportunities_tech": [{"id": "L1", "title": "iPhone 13", "listing_url": "u",
                                                   "asking_price": 200}], "deals": []}

    def table(self, name):
        return Q(self, name)


print("Parsing:")
ck("callback valido", bot.parse_callback("fr:b:t:L1"), ("b", "t", "L1"))
ck("callback estraneo", bot.parse_callback("altro:b:t:L1"), None)
ck("solo cifra", bot.parse_reply("230"), (None, 230.0))
ck("comprato 230 €", bot.parse_reply("comprato 230 €"), ("b", 230.0))
ck("offerto 199,50", bot.parse_reply("offerto 199,50"), ("o", 199.5))
ck("venduto", bot.parse_reply("Venduto a 410"), ("v", 410.0))
ck("sfumato senza cifra", bot.parse_reply("sfumato"), ("f", None))
ck("testo qualsiasi", bot.parse_reply("ciao come va"), None)

print("Azioni → pipeline:")
bot._estimate  # noqa: B018
import backend.services.reads as reads  # noqa: E402

reads.enrich_for_alerts = lambda cat, rows, db: [{"fairValue": 320, "suggestedOffer": 180,
                                                   "netMarginAfterCostsEur": None, "marketAvg": 320,
                                                   "askingPrice": 200, "maxBid": 230}]
db = FakeDB()
ck("contattato crea l'affare", bot.apply_action(db, "t", "L1", "c").startswith("📞"), True)
ck("una sola riga in pipeline", len(db.data["deals"]), 1)
ck("stadio contattato", db.data["deals"][0]["stage"], "contattato")
ck("stima fotografata", db.data["deals"][0]["estimate"]["marginEur"], 120)
bot.apply_action(db, "t", "L1", "b", 210)
ck("comprato a 210", (db.data["deals"][0]["stage"], db.data["deals"][0]["buy_price"]), ("comprato", 210))
ck("stesso affare, non un doppione", len(db.data["deals"]), 1)
bot.apply_action(db, "t", "L1", "x")
ck("scarta = triage", db.data["live_opportunities_tech"][0]["triage"], "scartato")

print("Messaggio d'offerta da copiare:")
from backend.services.notifications import offer_message  # noqa: E402

ck("cifra = offerta consigliata a 5 €", "a 385 €" in (offer_message(
    {"askingPrice": 420, "suggestedOffer": 384.7}, "smartphone") or ""), True)
ck("senza offerta: 90% del tetto", "a 145 €" in (offer_message(
    {"askingPrice": 200, "maxBid": 160}, "smartphone", repair=True) or ""), True)
ck("da riparare: 'così com'è'", "così com'è" in (offer_message(
    {"askingPrice": 200, "maxBid": 160}, "smartphone", repair=True) or ""), True)
ck("mai sopra il prezzo chiesto", "al prezzo indicato" in (offer_message(
    {"askingPrice": 300, "suggestedOffer": 310}, "smartphone") or ""), True)
ck("auto: centinaia e visione", "offrirei 8.300 €" in (offer_message(
    {"askingPrice": 9000, "suggestedOffer": 8330}, "automobile") or ""), True)
ck("niente cifra, niente messaggio", offer_message({"askingPrice": 300}, "smartphone"), None)

print(f"\n=== {_p} PASS / {_f} FAIL ===")
raise SystemExit(1 if _f else 0)
