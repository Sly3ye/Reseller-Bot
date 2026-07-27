"""Seed della GAMMA iPhone completa in target_models (copertura totale del mercato).

Obiettivo: coprire quasi la totalità degli annunci iPhone attivi su Subito.
Genera un target per ogni modello della gamma (ogni generazione × variante:
base/mini/Plus/Pro/Pro Max, più i modelli storici e SE). Il resolver di variante
canonica segmenta poi per (modello, memoria) in lettura; qui bastano le query.

Idempotente: upsert su (category, query). NON tocca i target auto.
NON disattiva target esistenti fuori dalla gamma (solo aggiunge/aggiorna).

Esegui dalla root:
  python scripts/seed_iphone_targets.py            # attiva tutti
  python scripts/seed_iphone_targets.py --from 12  # solo da iPhone 12 in su
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Generazioni "numeriche" → varianti Apple prodotte per quella generazione.
_GENERATIONS: dict[int, list[str]] = {
    11: ["", "Pro", "Pro Max"],
    12: ["mini", "", "Pro", "Pro Max"],
    13: ["mini", "", "Pro", "Pro Max"],
    14: ["", "Plus", "Pro", "Pro Max"],
    15: ["", "Plus", "Pro", "Pro Max"],
    16: ["", "Plus", "Pro", "Pro Max"],
}
# Modelli speciali/storici (numero non lineare) col loro "peso" di generazione
# per il filtro --from (X/XR/XS ≈ gen 10, SE ~ trasversale).
_SPECIAL: list[tuple[int, str]] = [
    (8, "iPhone 8"),
    (8, "iPhone 8 Plus"),
    (10, "iPhone X"),
    (10, "iPhone XR"),
    (10, "iPhone XS"),
    (10, "iPhone XS Max"),
    (16, "iPhone 16e"),
    (11, "iPhone SE"),  # SE 2020/2022: una query li cattura entrambi
]


def build_iphone_targets(min_gen: int = 0) -> list[dict]:
    """Costruisce la lista di target iPhone (query uniche), filtrando per generazione."""
    queries: list[str] = []
    for gen, variants in _GENERATIONS.items():
        if gen < min_gen:
            continue
        for v in variants:
            queries.append(f"iPhone {gen} {v}".strip())
    for gen, query in _SPECIAL:
        if gen >= min_gen:
            queries.append(query)

    # Dedup preservando l'ordine.
    seen: set[str] = set()
    targets: list[dict] = []
    for q in queries:
        if q in seen:
            continue
        seen.add(q)
        targets.append(
            {
                "category": "smartphone",
                "query": q,
                "strict_filters": {},
                "is_active": True,
            }
        )
    return targets


def main() -> None:
    min_gen = 0
    if "--from" in sys.argv:
        try:
            min_gen = int(sys.argv[sys.argv.index("--from") + 1])
        except (IndexError, ValueError):
            print("Uso: python scripts/seed_iphone_targets.py [--from N]")
            raise SystemExit(1)

    targets = build_iphone_targets(min_gen)

    from backend.core.database import get_db  # import qui: non serve per la lista

    db = get_db()
    try:
        result = (
            db.table("target_models")
            .upsert(targets, on_conflict="category,query")
            .execute()
        )
    except Exception as exc:
        if "target_models" in str(exc):
            print(
                "ERRORE: 'target_models' non esiste. Applica lo schema "
                "(database/selfhosted/init.sql; con Docker è automatico)."
            )
            raise SystemExit(1)
        raise

    rows = result.data or targets
    print(f"Seed gamma iPhone OK: {len(rows)} target attivi (da gen {min_gen or 8}).")
    for t in targets:
        print(f"  - {t['query']}")


if __name__ == "__main__":
    main()
