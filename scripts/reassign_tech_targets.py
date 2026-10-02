"""Riassegna le righe tech al target del LORO modello (correzione storica).

Il vecchio Sniper per target salvava ogni annuncio sotto il target della query
che l'aveva trovato: un "iPhone 13 Pro" uscito cercando "iPhone 13" finiva nel
target iPhone 13, e le statistiche per modello (venduti, tempo di vendita,
Market Intelligence) mescolavano modelli diversi. Qui ogni riga va al target
del modello nel titolo, con la stessa regola della ricerca ampia
(``services/sweep.match_target``).

Prudente: se il titolo non permette di riconoscere un modello, il target
attuale resta. Default dry-run (mostra cosa cambierebbe); --apply scrive.

Esegui dalla root:
  python scripts/reassign_tech_targets.py           # anteprima
  python scripts/reassign_tech_targets.py --apply   # applica
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.database import get_db  # noqa: E402
from backend.services.sweep import build_target_index, match_target  # noqa: E402
from backend.services.variants import backfill_existing, iphone_model_key  # noqa: E402

TABLE = "live_opportunities_tech"


def main() -> None:
    apply = "--apply" in sys.argv
    db = get_db()
    targets = db.table("target_models").select("id, query, category").eq(
        "category", "smartphone"
    ).execute().data or []
    names = {t["id"]: t["query"] for t in targets}
    index = build_target_index(targets)

    rows: list[dict] = []
    start = 0
    while True:
        page = (
            db.table(TABLE).select("id, title, target_id")
            .range(start, start + 999).execute().data or []
        )
        rows.extend(page)
        if len(page) < 1000:
            break
        start += 1000

    moves: dict[str | None, list[str]] = {}
    flows: Counter = Counter()
    for row in rows:
        target = match_target(row.get("title"), index)
        if target is None and iphone_model_key(row.get("title")) is None:
            continue  # modello non riconoscibile: si lascia com'è
        new_id = target["id"] if target else None
        if new_id == row.get("target_id"):
            continue
        moves.setdefault(new_id, []).append(row["id"])
        flows[(names.get(row.get("target_id"), "—"), names.get(new_id, "nessun target"))] += 1

    moved = sum(len(ids) for ids in moves.values())
    print(f"{len(rows)} righe tech, {moved} da riassegnare ({moved / max(len(rows), 1):.0%})\n")
    for (old, new), n in flows.most_common(25):
        print(f"  {n:>5}  {old:<20} → {new}")
    if not apply:
        print("\nAnteprima: niente scritto. Rilancia con --apply.")
        return
    for new_id, ids in moves.items():
        for i in range(0, len(ids), 500):
            db.table(TABLE).update({"target_id": new_id}).in_("id", ids[i:i + 500]).execute()
    print(f"\nFatto: {moved} righe riassegnate. Le medie per target si aggiornano al "
          f"prossimo Motore Notturno.")
    # Il resolver è cambiato insieme (refusi "I phone", linea Air unificata in
    # iphone-air): si ricalcolano anche variant_key/condition_tier/colore.
    print("Ricalcolo varianti…", backfill_existing())


if __name__ == "__main__":
    main()
