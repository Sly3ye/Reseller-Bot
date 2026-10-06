"""Test offline dell'analisi AI v3: unione guasti regex + AI, validazione
dell'output del modello, aggiornamento di condizione e variante.

Esegui dalla root:  python scripts/test_ai_merge.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.services.ai_analysis import (  # noqa: E402
    AI_VERSION, PROMPT_TECH, _field_writeback, coerce_analysis, ollama_payload,
)
from backend.services.defects import AI_TRUSTED_DEFAULT, GUASTI, merge_ai_defects  # noqa: E402

ALL = set(GUASTI) | {"parti-non-originali", "per-ricambi", "segni-estetici"}

PASS = FAIL = 0


def ck(desc, got, want):
    global PASS, FAIL
    ok = got == want
    PASS, FAIL = PASS + ok, FAIL + (not ok)
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}: {got}" + ("" if ok else f"  (atteso {want})"))


def ai(guasti=(), parti=(), segni=False, ricambi=False):
    return {"guasti": list(guasti), "parti_non_originali": list(parti),
            "segni_estetici": segni, "per_ricambi": ricambi}


print("merge_ai_defects")
ck("senza analisi v3 → invariato", merge_ai_defects(["graffi"], ["X"], {"sintesi": "ok"}), (["graffi"], ["X"]))
ck("analisi assente → invariato", merge_ai_defects(None, None, None), ([], []))
ck("aggiunge il guasto mancante", merge_ai_defects(["schermo-rotto"], [], ai(["schermo", "batteria"]), ALL)[0],
   ["schermo-rotto", "batteria-esausta"])
ck("non duplica", merge_ai_defects(["schermo-rotto"], [], ai(["schermo"]), ALL)[0], ["schermo-rotto"])
ck("AI senza guasti non toglie quelli delle regex", merge_ai_defects(["acqua"], [], ai())[0], ["acqua"])
ck("per ricambi e segni estetici", merge_ai_defects([], [], ai(segni=True, ricambi=True), ALL)[0],
   ["graffi", "per-ricambi"])
ck("parti non originali → features", merge_ai_defects([], ["Pari-al-Nuovo"], ai(parti=["schermo"]))[1],
   ["Pari-al-Nuovo", "Schermo-Non-Originale"])
ck("guasto fuori tassonomia ignorato", merge_ai_defects([], [], ai(["boh"]), ALL)[0], [])
ck("default: solo i guasti affidabili", merge_ai_defects([], [], ai(["schermo", "altro", "acqua", "face-id"]))[0],
   ["acqua", "face-id-rotto"])
ck("default: segni estetici dell'AI non contano", merge_ai_defects([], [], ai(segni=True))[0], [])
ck("default: parti non originali sì", merge_ai_defects([], [], ai(parti=["batteria"]))[1], ["Batteria-Non-Originale"])
ck("fiducia ristretta: niente parti", merge_ai_defects([], [], ai(parti=["batteria"]), {"acqua"})[1], [])
ck("default misurato senza schermo/altro", {"schermo", "altro", "batteria"} & set(AI_TRUSTED_DEFAULT), set())

print("coerce_analysis")
raw = {"guasti": ["Schermo", "face id", "inventato"], "parti_non_originali": "batteria",
       "segni_estetici": "sì", "per_ricambi": False, "rischio_truffa": "ALTO",
       "categoria_motivo": "difetto", "riparabile": "true", "sintesi": "x"}
a = coerce_analysis(raw)
ck("guasti normalizzati sulla tassonomia", a["guasti"], ["face-id", "schermo"])
ck("parti da stringa", a["parti_non_originali"], ["batteria"])
ck("booleani dal testo", (a["segni_estetici"], a["per_ricambi"], a["riparabile"]), (True, False, True))
ck("rischio normalizzato", a["rischio_truffa"], "alto")
ck("versione", a["v"], AI_VERSION)
ck("riparabile e nota dai guasti", (a["riparabile"], a["nota_riparazione"]), (True, "face-id, schermo"))
r = coerce_analysis({"guasti": ["acqua", "bloccato"], "riparabile": True})
ck("solo guasti a rischio → non riparabile (il modello non decide)", (r["riparabile"], r["nota_riparazione"]), (False, ""))
ck("per ricambi → non riparabile", coerce_analysis({"guasti": ["schermo"], "per_ricambi": True})["riparabile"], False)
ck("auto: niente guasti iPhone", "guasti" in coerce_analysis(raw, "automobile"), False)

print("prompt e richiesta")
ck("prompt con guasti e campi tech", all(k in PROMPT_TECH for k in ('"guasti"', '"sintesi"', '"storage_gb"', "{title}")), True)
payload = ollama_payload("p", "m")
ck("niente ragionamento, JSON, deterministico",
   (payload["think"], payload["format"], payload["options"]["temperature"]), (False, "json", 0))

print("_field_writeback")
row = {"title": "iPhone 13 128GB", "description": "vetro rotto", "storage_gb": 128,
       "defects_noted": [], "features": [], "variant_key": "iphone-13-128", "condition_tier": "buono"}
up = _field_writeback(row, {}, row["title"], coerce_analysis({"guasti": ["acqua"]}))
ck("guasto affidabile dall'AI → difetti e condizione rotto",
   (up.get("defects_noted"), up.get("condition_tier")), (["acqua"], "rotto"))
ck("guasto non affidabile → condizione invariata",
   _field_writeback(row, {}, row["title"], coerce_analysis({"guasti": ["schermo"]})), {})
ck("variante invariata non riscritta", "variant_key" in up, False)
ck("niente da cambiare → update vuoto",
   _field_writeback({**row, "defects_noted": ["schermo-rotto"], "condition_tier": "rotto"}, {}, row["title"],
                    coerce_analysis({"guasti": ["schermo"]})), {})
up = _field_writeback({**row, "storage_gb": None, "variant_key": "iphone-13"}, {"storage_gb": 256}, row["title"],
                      coerce_analysis({"guasti": []}))
ck("memoria dall'AI → variante per memoria", (up.get("storage_gb"), up.get("variant_key")), (256, "iphone-13-256"))

print(f"\n=== {PASS} PASS / {FAIL} FAIL ===")
sys.exit(1 if FAIL else 0)
