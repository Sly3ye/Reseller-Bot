"""Seed idempotente dei target pilota nella tabella target_models (via API Supabase).

Prerequisito: applica prima database/05_target_models.sql (crea la tabella; la
migrazione stessa fa già il seed). Questo script è utile per re-seedare o
aggiornare i target a comando.

Esegui dalla root:  python scripts/seed_target_models.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.database import get_supabase_client  # noqa: E402

TARGETS = [
    {
        "category": "automobile",
        "query": "Golf GTI",
        "strict_filters": {
            "min_year": 2017,
            "max_year": 2020,
            "max_km": 100000,
            "transmission": "automatic",
        },
        "is_active": True,
    },
    {
        "category": "smartphone",
        "query": "iPhone 14",
        "strict_filters": {},
        "is_active": True,
    },
]


def main() -> None:
    db = get_supabase_client()
    try:
        result = (
            db.table("target_models")
            .upsert(TARGETS, on_conflict="category,query")
            .execute()
        )
    except Exception as exc:
        if "target_models" in str(exc):
            print(
                "ERRORE: la tabella 'target_models' non esiste ancora.\n"
                "Applica prima database/05_target_models.sql nell'SQL Editor "
                "di Supabase, poi rilancia questo script."
            )
            raise SystemExit(1)
        raise

    print(f"Seed target_models OK ({len(result.data or [])} record):")
    for row in result.data or []:
        print(
            f"  - {row['category']:11} | {row['query']:12} | "
            f"active={row['is_active']} | filters={row['strict_filters']}"
        )


if __name__ == "__main__":
    main()
