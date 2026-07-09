"""Inserisce il target auto 'Golf VII GTI' con i suoi strict_filters nativi.

Prerequisito: applica prima database/04_add_automobile_category.sql (aggiunge
il valore 'automobile' all'enum product_category), altrimenti l'insert fallisce.

Esegui:  python scripts/seed_car_target.py
"""

from backend.tasks import get_or_create_product

CATEGORY = "automobile"
QUERY = "Golf VII GTI"
STRICT_FILTERS = {
    "min_year": 2017,
    "max_km": 100000,
    "transmission": "automatic",
}


def main() -> None:
    product, created = get_or_create_product(
        QUERY,
        CATEGORY,
        specs={"strict_filters": STRICT_FILTERS},
    )
    action = "creato" if created else "già presente"
    print(f"Target auto {action}: id={product['id']}")
    print(f"  category={product.get('category')} | model={product.get('model')}")
    print(f"  specs={product.get('specs')}")


if __name__ == "__main__":
    main()
