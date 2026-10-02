"""Misura il riconoscimento dei guasti sulla serie etichettata a mano
(scripts/data/eval_guasti*.json: 145 di sviluppo + 99 di verifica, mai
usati per scrivere le regex).

Valuta le regex dell'NLP e/o uno o più modelli AI locali (Ollama), con le
stesse metriche, così la scelta del modello si fa sui numeri:
- guasti: precisione / richiamo / F1 (micro) e F1 per singolo guasto;
- parti non originali: idem;
- segni estetici e "per ricambi": accuratezza;
- annunci perfetti (zero errori su guasti), JSON validi, secondi per annuncio.

Esegui dalla root:
  python scripts/eval_guasti.py                       # solo regex (nessun Ollama)
  python scripts/eval_guasti.py --models gemma4:26b,qwen3.5:9b,llama3
  python scripts/eval_guasti.py --models gemma4:26b --ollama http://localhost:11434

Sul Mac: `ollama pull <modello>` prima, e Ollama aperto.
"""

import argparse
import json
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from backend.scrapers.nlp_parser import parse_listing  # noqa: E402
from backend.services.defects import GUASTI, PARTI, PROMPT_V2, coerce_ai_v2, from_nlp  # noqa: E402

SETS = {
    "sviluppo": ROOT / "scripts" / "data" / "eval_guasti.json",          # usata per scrivere le regex
    "verifica": ROOT / "scripts" / "data" / "eval_guasti_holdout.json",  # mai vista: misura onesta
}


def prf(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if tp + fp else 1.0
    r = tp / (tp + fn) if tp + fn else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def score(items: list[dict], preds: list[dict | None]) -> dict:
    out: dict = {"n": len(items), "invalid": sum(1 for p in preds if p is None)}
    for field, labels in (("guasti", GUASTI), ("parti_non_originali", PARTI)):
        tp = fp = fn = 0
        per = {lab: Counter() for lab in labels}
        for it, pred in zip(items, preds):
            gold = set(it["label"][field])
            got = set((pred or {}).get(field, []))
            tp += len(gold & got); fp += len(got - gold); fn += len(gold - got)
            for lab in labels:
                per[lab]["tp"] += lab in gold and lab in got
                per[lab]["fp"] += lab in got and lab not in gold
                per[lab]["fn"] += lab in gold and lab not in got
        out[field] = prf(tp, fp, fn)
        out[field + "_per"] = {
            lab: (prf(c["tp"], c["fp"], c["fn"])[2], c["tp"] + c["fn"])
            for lab, c in per.items() if c["tp"] + c["fn"] + c["fp"]
        }
    for field in ("segni_estetici", "per_ricambi"):
        ok = sum(1 for it, p in zip(items, preds) if p is not None and p[field] == it["label"][field])
        out[field] = ok / len(items)
    out["perfetti"] = sum(
        1 for it, p in zip(items, preds)
        if p is not None and set(p["guasti"]) == set(it["label"]["guasti"])
    ) / len(items)
    return out


def predict_regex(it: dict) -> dict:
    parsed = parse_listing(it["title"], it["description"])
    return from_nlp(parsed["defects_noted"], parsed["features"])


def predict_ollama(it: dict, model: str, url: str) -> dict | None:
    import httpx

    prompt = PROMPT_V2.format(title=it["title"] or "", description=it["description"] or "")
    try:
        r = httpx.post(
            f"{url}/api/generate",
            json={"model": model, "prompt": prompt, "format": "json", "stream": False,
                  "options": {"temperature": 0}},
            timeout=180,
        )
        r.raise_for_status()
        return coerce_ai_v2(json.loads(r.json()["response"]))
    except Exception as exc:  # JSON non valido, timeout, modello assente
        print(f"    ! {model}: {type(exc).__name__}: {str(exc)[:80]}")
        return None


def report(name: str, s: dict, secs: float | None) -> None:
    g, p = s["guasti"], s["parti_non_originali"]
    print(f"\n=== {name}" + (f"  ({secs:.1f}s/annuncio)" if secs else ""))
    print(f"  guasti        P {g[0]:.2f}  R {g[1]:.2f}  F1 {g[2]:.2f}   annunci perfetti {s['perfetti']:.0%}")
    print(f"  non originali P {p[0]:.2f}  R {p[1]:.2f}  F1 {p[2]:.2f}")
    print(f"  segni estetici acc {s['segni_estetici']:.0%}   per ricambi acc {s['per_ricambi']:.0%}"
          f"   JSON non validi {s['invalid']}")
    per = ", ".join(f"{k} {f:.2f} (n={n})" for k, (f, n) in sorted(s["guasti_per"].items(), key=lambda x: -x[1][1]))
    print(f"  F1 per guasto: {per}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", default="")
    ap.add_argument("--ollama", default="http://localhost:11434")
    ap.add_argument("--no-regex", action="store_true")
    ap.add_argument("--show-errors", type=int, default=0, help="mostra N errori sui guasti")
    ap.add_argument("--set", choices=[*SETS, "tutte"], default="verifica")
    args = ap.parse_args()

    names = list(SETS) if args.set == "tutte" else [args.set]
    items = [it for n in names for it in json.loads(SETS[n].read_text(encoding="utf-8"))["items"]]
    print(f"serie: {', '.join(names)} ({len(items)} annunci)")
    runs: list[tuple[str, list, float | None]] = []
    if not args.no_regex:
        runs.append(("regex (NLP)", [predict_regex(it) for it in items], None))
    for model in [m.strip() for m in args.models.split(",") if m.strip()]:
        print(f"{model}: {len(items)} annunci…")
        t0 = time.time()
        preds = []
        for i, it in enumerate(items, 1):
            preds.append(predict_ollama(it, model, args.ollama))
            if i % 25 == 0:
                print(f"  {i}/{len(items)}")
        runs.append((model, preds, (time.time() - t0) / len(items)))

    for name, preds, secs in runs:
        report(name, score(items, preds), secs)
        if args.show_errors:
            shown = 0
            for it, p in zip(items, preds):
                got = set((p or {}).get("guasti", []))
                if got != set(it["label"]["guasti"]) and shown < args.show_errors:
                    shown += 1
                    print(f"    ✗ {it['title'][:40]!r}: atteso {sorted(it['label']['guasti'])} letto {sorted(got)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
