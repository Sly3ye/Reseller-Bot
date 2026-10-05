"""Ricalcola la variante (modello@generazione) di tutte le righe auto e
corregge i km scritti in migliaia ("184" → 184.000, vedi valuation.normalize_km).

Serve quando cambia ``backend/data/car_generations.json`` o il resolver auto:
le righe vecchie restano altrimenti con la variante dell'epoca (prima: lo
slug del target, un unico pool dal 2007 al 2026).

Esegui dalla root (meglio nel container):
  python scripts/backfill_car_variants.py            # anteprima
  python scripts/backfill_car_variants.py --apply
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.database import _get_pool  # noqa: E402
from backend.services.valuation import normalize_km  # noqa: E402
from backend.services.variants import resolve_variant  # noqa: E402

TABLE = "live_opportunities_auto"


def main() -> int:
    apply = "--apply" in sys.argv
    with _get_pool().connection() as conn:
        rows = conn.execute(
            f"select a.id, a.title, a.description, a.year, a.km, a.variant_key, a.defects_noted, "
            f"a.features, a.status, t.query, t.strict_filters "
            f"from public.{TABLE} a left join public.target_models t on t.id = a.target_id"
        ).fetchall()

    after: Counter = Counter()
    changes = []
    for r in rows:
        km = normalize_km(r["km"], r["year"])
        res = resolve_variant(
            "automobile", r["title"],
            {"year": r["year"], "km": km, "defects_noted": r["defects_noted"] or [],
             "features": r["features"] or []},
            query=r["query"], strict_filters=r["strict_filters"], description=r["description"],
        )
        after[res["variant_key"]] += 1
        if res["variant_key"] != r["variant_key"] or km != r["km"]:
            changes.append((res["variant_key"], km, r["id"]))

    km_fixed = sum(1 for r in rows if normalize_km(r["km"], r["year"]) != r["km"])
    print(f"{len(rows)} righe auto, {len(changes)} cambiano ({km_fixed} km corretti da migliaia)")
    for key, n in sorted(after.items()):
        print(f"  {n:>5}  {key}")
    if not apply:
        print("\nAnteprima: niente scritto. Rilancia con --apply.")
        return 0
    with _get_pool().connection() as conn, conn.cursor() as cur:
        cur.executemany(f"update public.{TABLE} set variant_key = %s, km = %s where id = %s", changes)
    print(f"\nFatto: {len(changes)} righe aggiornate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
