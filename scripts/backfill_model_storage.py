"""Riapplica il riconoscimento corrente di MEMORIA e MODELLO a tutto l'archivio
tech: aggiorna storage_gb, variant_key e target_id.

Serve quando l'estrazione migliora (es. "256 g", "GB 128", "iPhone 12 Pro 128"
nudo nel titolo, modello letto dalla descrizione se il titolo dice solo
"iPhone"): le righe vecchie restano altrimenti con il riconoscimento
dell'epoca e le statistiche per variante le perdono.

Regole prudenti:
- memoria: si riempie se manca; se c'è già (magari dall'AI) si sovrascrive
  solo quando il TITOLO la dichiara con l'unità ed è diversa (es. la vecchia
  regola dava 1TB a "iPhone 14 Pro 512GB" se in descrizione c'era "1 TB");
- target: si cambia solo se il modello è riconosciuto (titolo o descrizione).

Esegui dalla root (meglio nel container):
  python scripts/backfill_model_storage.py            # anteprima
  python scripts/backfill_model_storage.py --apply
"""

import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.database import _get_pool  # noqa: E402
from backend.scrapers.nlp_parser import _extract_storage_gb, _storage_with_unit  # noqa: E402
from backend.services.sweep import build_target_index, match_target  # noqa: E402
from backend.services.variants import iphone_model_key, model_text, resolve_variant  # noqa: E402

TABLE = "live_opportunities_tech"


def main() -> int:
    apply = "--apply" in sys.argv
    with _get_pool().connection() as conn:
        targets = conn.execute(
            "select id, query, category from public.target_models where category = 'smartphone'"
        ).fetchall()
        rows = conn.execute(
            f"select id, title, description, storage_gb, variant_key, target_id, "
            f"defects_noted, features, status from public.{TABLE}"
        ).fetchall()
    index = build_target_index(targets)

    stats: Counter = Counter()
    changes = []
    for r in rows:
        storage = r["storage_gb"]
        found = _extract_storage_gb(r["title"], r["description"])
        if storage is None and found is not None:
            storage = found
            stats["memoria riempita"] += 1
        elif storage is not None and found is not None and found != storage:
            in_title = _storage_with_unit(r["title"] or "")
            if in_title is not None and in_title != storage:
                storage = in_title
                stats["memoria corretta dal titolo"] += 1

        variant = resolve_variant(
            "smartphone", r["title"],
            {"storage_gb": storage, "defects_noted": r["defects_noted"] or [],
             "features": r["features"] or []},
            description=r["description"],
        )["variant_key"]

        target_id = r["target_id"]
        mtext = model_text(r["title"], r["description"])
        if iphone_model_key(mtext) and not iphone_model_key(r["title"]):
            stats["modello dalla descrizione"] += 1
        target = match_target(mtext, index)
        if target is not None or iphone_model_key(mtext):
            new_tid = target["id"] if target else None
            if new_tid != target_id:
                target_id = new_tid
                stats["target cambiato"] += 1

        if variant != r["variant_key"]:
            stats["variante cambiata"] += 1
        if (storage, variant, target_id) != (r["storage_gb"], r["variant_key"], r["target_id"]):
            changes.append((storage, variant, target_id, r["id"]))

    active = [r for r in rows if r["status"] in ("nuovo", "visto")]
    by_id = {c[3]: c for c in changes}
    st_after = sum(1 for r in active if (by_id[r["id"]][0] if r["id"] in by_id else r["storage_gb"]))
    print(f"{len(rows)} righe, {len(changes)} cambiano")
    for k, n in stats.most_common():
        print(f"  {n:>6}  {k}")
    if active:
        st_before = sum(1 for r in active if r["storage_gb"])
        print(f"memoria sugli attivi: {st_before / len(active):.1%} → {st_after / len(active):.1%}")
    if not apply:
        print("\nAnteprima: niente scritto. Rilancia con --apply.")
        return 0
    with _get_pool().connection() as conn:
        with conn.cursor() as cur:
            cur.executemany(
                f"update public.{TABLE} set storage_gb = %s, variant_key = %s, "
                f"target_id = %s where id = %s",
                changes,
            )
    print(f"\nFatto: {len(changes)} righe aggiornate. Medie e statistiche per variante "
          f"si aggiornano al prossimo Motore Notturno.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
