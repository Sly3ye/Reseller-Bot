"""Inserisce il target auto 'Golf VII GTI' con i suoi strict_filters nativi.

Prerequisito: applica prima database/04_add_automobile_category.sql (aggiunge
il valore 'automobile' all'enum product_category), altrimenti l'insert fallisce.

Esegui dalla root del progetto:  python scripts/seed_car_target.py
"""

import sys
from pathlib import Path

# Permette di lanciare lo script direttamente: aggiunge la root del progetto
# a sys.path così "import backend" funziona anche senza "python -m".
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.tasks import get_or_create_product  # noqa: E402

CATEGORY = "automobile"
QUERY = "Golf VII GTI"
STRICT_FILTERS = {
    "min_year": 2017,
    "max_km": 100000,
    "transmission": "automatic",
}


def main() -> None:
    try:
        product, created = get_or_create_product(
            QUERY,
            CATEGORY,
            specs={"strict_filters": STRICT_FILTERS},
        )
    except Exception as exc:
        message = str(exc)
        if "automobile" in message or "invalid input value for enum" in message:
            print(
                "ERRORE: la categoria 'automobile' non esiste ancora nel DB.\n"
                "Applica prima database/04_add_automobile_category.sql "
                "nell'SQL Editor di Supabase, poi rilancia questo script."
            )
            raise SystemExit(1)
        raise

    action = "creato" if created else "già presente"
    print(f"Target auto {action}: id={product['id']}")
    print(f"  category={product.get('category')} | model={product.get('model')}")
    print(f"  specs={product.get('specs')}")


if __name__ == "__main__":
    main()
