"""Riapplica l'NLP corrente (guasti v2, negazioni, parti non originali) a TUTTE
le righe già in archivio: aggiorna defects_noted, features e condition_tier.

Serve ogni volta che il riconoscimento migliora: le righe vecchie restano
altrimenti con la classificazione dell'epoca. I guasti letti dall'AI (salvati
in ai_analysis) vengono riaggiunti a quelli delle regex, non persi. Non tocca memoria/colore/batteria
(alcuni li ha riempiti l'AI) né la variante.

Esegui dalla root (meglio nel container):
  python scripts/reparse_nlp.py            # anteprima: fasce prima → dopo
  python scripts/reparse_nlp.py --apply
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg.types.json import Jsonb  # noqa: E402

from backend.core.database import _get_pool, get_db  # noqa: E402
from backend.scrapers.nlp_parser import parse_listing  # noqa: E402
from backend.services.defects import merge_ai_defects  # noqa: E402
from backend.services.variants import condition_tier  # noqa: E402

TABLE = "live_opportunities_tech"


def main() -> int:
    apply = "--apply" in sys.argv
    db = get_db()
    rows, start = [], 0
    while True:
        page = (db.table(TABLE).select("id, title, description, defects_noted, features, condition_tier, ai_analysis")
                .order("id").range(start, start + 4999).execute().data or [])
        rows += page
        if len(page) < 5000:
            break
        start += 5000

    before, after, moves = Counter(), Counter(), Counter()
    changes = []
    for r in rows:
        parsed = parse_listing(r["title"], r["description"])
        defects, features = merge_ai_defects(parsed["defects_noted"], parsed["features"], r.get("ai_analysis"))
        tier = condition_tier("smartphone", defects, features)
        before[r["condition_tier"]] += 1
        after[tier] += 1
        if tier != r["condition_tier"]:
            moves[(r["condition_tier"], tier)] += 1
        if (tier != r["condition_tier"] or sorted(defects) != sorted(r["defects_noted"] or [])
                or sorted(features) != sorted(r["features"] or [])):
            changes.append((Jsonb(defects), Jsonb(features), tier, r["id"]))

    print(f"{len(rows)} righe, {len(changes)} cambiano")
    print("fasce prima:", dict(before.most_common()))
    print("fasce dopo: ", dict(after.most_common()))
    for (a, b), n in moves.most_common(10):
        print(f"  {n:>6}  {a} → {b}")
    if not apply:
        print("\nAnteprima: niente scritto. Rilancia con --apply.")
        return 0
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"update public.{TABLE} set defects_noted = %s, features = %s, "
                f"condition_tier = %s where id = %s",
                changes,
            )
    print(f"\nFatto: {len(changes)} righe aggiornate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
