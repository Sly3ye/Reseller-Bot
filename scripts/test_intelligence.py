"""Test delle funzioni pure di intelligence (NLP + scoring), zero dipendenze DB.

Carica i moduli per path così girano anche senza psycopg/imagehash installati.
Esegui dalla root:  python scripts/test_intelligence.py
"""

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))  # scoring importa services.parts / variants (senza DB)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


nlp = _load("nlp_parser", "backend/scrapers/nlp_parser.py")
scoring = _load("scoring", "backend/services/scoring.py")

_passed = 0
_failed = 0


def check(desc, got, want):
    global _passed, _failed
    ok = got == want
    _passed += ok
    _failed += not ok
    mark = "OK  " if ok else "FAIL"
    extra = "" if ok else f"  (atteso {want})"
    print(f"  {mark} {desc}: {got}{extra}")


def test_nlp_tech():
    print("NLP tech:")
    r = nlp.parse_listing("iPhone 13 Pro 256GB", "batteria 89%, scatola e fattura")
    check("storage", r["storage_gb"], 256)
    check("batteria", r["battery_pct"], 89)
    check("corredo", set(r["features"]), {"Scatola", "Fattura"})
    r = nlp.parse_listing("iPhone 12 per ricambi", "schermo rotto e icloud bloccato")
    check("difetti", set(r["defects_noted"]), {"per-ricambi", "schermo-rotto", "icloud-bloccato"})
    check("exclude_iqr", r["exclude_from_iqr"], True)
    r = nlp.parse_listing("iPhone 15 Pro Max 1TB", "battery health 100%")
    check("storage_tb", r["storage_gb"], 1024)
    check("batteria_100", r["battery_pct"], 100)


def test_nlp_storage():
    print("NLP memoria (forme reali):")
    s = lambda t, desc=None: nlp.parse_listing(t, desc)["storage_gb"]  # noqa: E731
    check("128g", s("Iphone 15 pro 128g"), 128)
    check("256 g", s("iPhone 15 pro 256 g"), 256)
    check("512Gg", s("Iphone 17 pro 512Gg"), 512)
    check("128. Gb.", s("Iphone. 14. Plus. Black. 128. Gb. 330€"), 128)
    check("1 T", s("iPhone 13 pro max", "Vendo da 1 T Con scatola"), 1024)
    check("2TB", s("iPhone 17 Pro Max 2TB"), 2048)
    check("1000 giga", s("IPHONE 16 promax 1000 giga nero"), 1024)
    check("16gb vecchio", s("iPhone 3G nero 16gb"), 16)
    check("GB 128", s("iPhone 16", "Vendo Iphone 16 – GB 128 ad euro 550"), 128)
    check("256 MB = GB", s("I phone 13", "Vedo iPhone 13 bianco 256 MB"), 256)
    check("memoria 256", s("iPhone 13 Pro Max", "iPhone 13 Pro Max, 256 memoria."), 256)
    check("nudo nel titolo", s("iPhone 12 pro 128"), 128)
    check("titolo prima della descrizione", s("iPhone 14 Pro 512 gb", "disponibili anche 1TB"), 512)
    check("prezzo nel titolo ≠ memoria", s("Iphone 11 128€"), None)
    check("prezzo € prima", s("iPhone 11 € 256"), None)
    check("nudo dopo il modello in descrizione", s("Iphone", "iphone 14 128 in ottime condizioni"), 128)
    check("batteria% ≠ memoria", s("iPhone 13", "batteria 87%"), None)
    check("16 nudo non basta", s("iPhone 7 16"), None)


def test_nlp_guasti_v2():
    print("NLP guasti v2 (negazioni, parti non originali):")
    d = lambda t, desc="": nlp.parse_listing(t, desc)["defects_noted"]  # noqa: E731
    check("nessun graffio ≠ graffi", d("iPhone 13", "perfetto, nessun graffio"), [])
    check("nessun blocco iCloud ≠ bloccato", d("iPhone 15", "Nessun blocco iCloud, funzionante"), [])
    check("graffi veri", d("iPhone 13", "qualche piccolo graffio sul retro"), ["graffi"])
    check("display presenta lesioni", "schermo-rotto" in d("iPhone 12", "il display presenta lesioni"), True)
    check("ordine inverso", "schermo-rotto" in d("iPhone 11", "Non funziona lo schermo"), True)
    check("contrasto 'ma'", d("iPhone X", "Lo schermo è perfetto, ma non funziona il Face ID"), ["face-id-rotto"])
    check("pellicola rotta ≠ schermo", d("iPhone 13", "la pellicola sullo schermo è rotta"), [])
    check("senza scheda madre = guasto", "scheda-madre" in d("iPhone 14 Pro", "senza scheda madre, per ricambi"), True)
    check("caduto in mare", "acqua" in d("iPhone 15 Pro", "caduto in mare, non funzionante"), True)
    check("'unico problema' chiude la negazione",
          "schermo-rotto" in d("iPhone 11", "nessun difetto unico problema schermo un po crepato"), True)
    f = nlp.parse_listing("iPhone 13", "display compatibile, batteria non originale")["features"]
    check("parti non originali", {x for x in f if x.endswith("Non-Originale")},
          {"Schermo-Non-Originale", "Batteria-Non-Originale"})
    check("batteria sotto 70%", "batteria-esausta" in d("iPhone 12", "batteria 66%"), True)


def test_nlp_auto():
    print("NLP auto:")
    r = nlp.parse_listing("BMW 320d 2018 150.000 km", "M Sport, automatico, incidentata")
    check("km", r["km"], 150000)
    check("anno", r["year"], 2018)
    check("exclude_iqr", r["exclude_from_iqr"], True)


def test_scoring():
    print("Scoring:")
    ev = scoring.evaluate_opportunity(
        category="smartphone", title="iPhone 13 Pro Max", asking=300.0,
        market_avg=650.0, margin_pct=116.0, found_at="2026-07-17T11:00:00+00:00",
        seller_type="privato", defects=["schermo-rotto"], urgency=[],
        features=[], battery_pct=None, has_price_drop=False,
    )
    # Listini per modello (services/parts.py). Default: aftermarket, cioè lo
    # schermo Soft OLED del 13 Pro Max (41,30€ nel listino versionato).
    item = ev["repair"]["items"][0]
    check("repair_source default", item["source"], "aftermarket")
    check("repair_total aftermarket", ev["repair"]["total"], item["aftermarket"]["price"])
    check("net_margin", ev["repair"]["netMarginEur"], round(650.0 - 300.0 - item["aftermarket"]["price"], 2))
    # Colonna Apple: prezzo meno il credito di reso della parte vecchia.
    import backend.services.parts as parts
    parts.CONFIG["repair_source"] = "apple"
    ev_apple = scoring.evaluate_opportunity(
        category="smartphone", title="iPhone 13 Pro Max", asking=300.0,
        market_avg=650.0, margin_pct=116.0, found_at=None, seller_type="privato",
        defects=["schermo-rotto"], urgency=[], features=[], battery_pct=None, has_price_drop=False,
    )
    a = ev_apple["repair"]["items"][0]["apple"]
    check("apple netto = prezzo - credito", ev_apple["repair"]["total"], round(a["price"] - a["credit"], 2))
    # Con ricambio Apple la rivendita resta quella del sano (fattore 1).
    check("apple: rivendita piena",
          scoring.evaluate_opportunity(
              category="smartphone", title="iPhone 13 Pro Max", asking=300.0, market_avg=650.0,
              margin_pct=None, found_at=None, seller_type=None, defects=["schermo-rotto"], urgency=[],
              features=[], battery_pct=None, has_price_drop=False,
              non_original_ratios={"schermo": 0.844})["repair"]["resaleFactor"], 1.0)
    parts.CONFIG["repair_source"] = "aftermarket"
    # Aftermarket: si rivende al prezzo del sano × sconto misurato per lo schermo.
    ev_r = scoring.evaluate_opportunity(
        category="smartphone", title="iPhone 13 Pro Max", asking=300.0, market_avg=650.0,
        margin_pct=None, found_at=None, seller_type=None, defects=["schermo-rotto"], urgency=[],
        features=[], battery_pct=None, has_price_drop=False, non_original_ratios={"schermo": 0.844},
    )
    part_cost = ev_r["repair"]["items"][0]["cost"]
    check("rivendita riparato = sano × 0,844", ev_r["repair"]["resaleAfterRepair"], round(650 * 0.844))
    check("margine sul riparato", ev_r["repair"]["netMarginEur"], round(650 * 0.844 - 300 - part_cost, 2))
    # Il bug del doppio conteggio: il margine NON parte dal valore equo del rotto.
    ev_fv = scoring.evaluate_opportunity(
        category="smartphone", title="iPhone 13 Pro Max", asking=300.0, market_avg=650 * 0.55,
        margin_pct=None, found_at=None, seller_type=None, defects=["schermo-rotto"], urgency=[],
        features=[], battery_pct=None, has_price_drop=False, resale_ref=650.0,
    )
    check("base = sano, non valore equo del rotto", ev_fv["repair"]["netMarginEur"], round(650 - 300 - part_cost, 2))
    check("offer<asking", ev["suggestedOffer"] is not None and ev["suggestedOffer"] < 300, True)
    ev2 = scoring.evaluate_opportunity(
        category="automobile", title="Golf GTI", asking=17500.0, market_avg=21000.0,
        margin_pct=20.0, found_at="2026-07-15T10:00:00+00:00", seller_type="finto_privato",
        defects=["graffi", "grandine"], urgency=["realizzo"], features=[],
        battery_pct=None, has_price_drop=True,
    )
    check("penalty", ev2["defectPenaltyEur"], 1300)
    check("score_range", 0 <= ev2["score"] <= 100, True)
    check("offer_no_avg", scoring.suggested_offer("smartphone", None, 400), None)


def main() -> None:
    test_nlp_tech()
    test_nlp_storage()
    test_nlp_guasti_v2()
    test_nlp_auto()
    test_scoring()
    print(f"\n=== {_passed} PASS / {_failed} FAIL ===")
    raise SystemExit(1 if _failed else 0)


if __name__ == "__main__":
    main()
