"""Imposta la flotta di scraping ESATTA voluta ora, in modo idempotente.

Target attivi desiderati:
  - iPhone dalla generazione 13 in poi (13, 14, 15, 16, 17 + varianti mini/Plus/
    Air/Pro/Pro Max e 16e/17e).
  - Auto: solo BMW 123d e BMW 125i.

Cosa fa:
  1. Upsert (is_active=true) di tutti i target desiderati su (category, query).
  2. Disattiva (is_active=false) qualunque altro target attivo NON in questa
     lista — così i seed pilota (es. 'Golf GTI', 'iPhone 14' extra) non restano
     accesi a far scrapare cose che non vuoi. NON cancella nulla: solo spegne.

Le stesse `query` deterministiche servono anche al merge: il DB principale, se
seedato con gli stessi nomi, si allinea per (category, query). Vedi
scripts/merge_instances.py.

Esegui (con lo stack Docker su):
  docker compose exec backend python scripts/seed_targets.py
Oppure in locale con DATABASE_URL impostata:
  python scripts/seed_targets.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.seed_iphone_targets import build_iphone_targets  # noqa: E402

# --- Auto: solo i due BMW richiesti. Filtri vuoti = cattura ampia (l'auto è
# rimandata; qui si accumula soltanto). Se sul Mac hai usato query diverse,
# allinea questi nomi PRIMA di raccogliere, così il merge combacia. ---
CAR_TARGETS: list[dict] = [
    {"category": "automobile", "query": "BMW 123d", "strict_filters": {}, "is_active": True},
    {"category": "automobile", "query": "BMW 125i", "strict_filters": {}, "is_active": True},
]


def desired_targets() -> list[dict]:
    # iPhone dalla gen 13 in su (query identiche a quelle canoniche del progetto).
    iphones = build_iphone_targets(min_gen=13)
    return iphones + CAR_TARGETS


def main() -> None:
    targets = desired_targets()
    wanted_keys = {(t["category"], t["query"]) for t in targets}

    from backend.core.database import get_db

    db = get_db()

    # 1) Upsert dei desiderati (attivi).
    try:
        db.table("target_models").upsert(targets, on_conflict="category,query").execute()
    except Exception as exc:  # noqa: BLE001
        if "target_models" in str(exc):
            print(
                "ERRORE: 'target_models' non esiste. Applica lo schema "
                "(database/selfhosted/init.sql; con Docker è automatico al 1° avvio)."
            )
            raise SystemExit(1)
        raise

    # 2) Disattiva ogni altro target attualmente attivo non richiesto.
    existing = db.table("target_models").select("id, category, query, is_active").execute().data or []
    turned_off = 0
    for row in existing:
        key = (row["category"], row["query"])
        if key not in wanted_keys and row.get("is_active"):
            db.table("target_models").update({"is_active": False}).eq("id", row["id"]).execute()
            turned_off += 1

    iphone_n = len(targets) - len(CAR_TARGETS)
    print(f"Flotta impostata: {iphone_n} target iPhone (gen 13+) + {len(CAR_TARGETS)} auto (BMW 123d/125i) attivi.")
    if turned_off:
        print(f"Disattivati {turned_off} target non richiesti (es. seed pilota) — non cancellati.")
    print("\nTarget attivi:")
    for t in targets:
        print(f"  - [{t['category']}] {t['query']}")


if __name__ == "__main__":
    main()
