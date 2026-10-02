"""Cruscotto qualità del dato: quanto ci si può fidare delle metriche.

Le statistiche (valore equo, tempo di vendita, Market Intelligence) sono buone
quanto i dati sotto. Qui, per categoria:

- **copertura**: annunci che Subito dichiara (ultimo inventario) vs quelli
  che abbiamo visto, e annunci attivi in DB;
- **completezza dei campi** estratti dagli annunci attivi: memoria, colore,
  batteria, data di pubblicazione, foto, modello riconosciuto, target;
- **raccolta**: giri, richieste, blocchi e annunci persi nelle ultime 24h;
- **sparizioni** degli ultimi 7 giorni.

Una sola query aggregata per tabella (raw SQL: nomi di tabella dal codice,
mai dall'utente).
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TABLES = {"smartphone": "live_opportunities_tech", "automobile": "live_opportunities_auto"}


def _pct(part: Any, total: Any) -> float | None:
    return round(part / total * 100, 1) if total else None


def get_data_quality(category: str = "smartphone") -> dict[str, Any]:
    from backend.core.database import _get_pool, get_db, has_column  # noqa: PLC0415
    from backend.services.variants import iphone_model_key  # noqa: PLC0415

    table = TABLES["automobile" if category in ("automobile", "auto") else "smartphone"]
    tech = table.endswith("_tech")
    published = "count(published_at)" if has_column(table, "published_at") else "null"
    tech_cols = (
        "count(storage_gb) as storage, count(battery_pct) as battery,"
        if tech else "null as storage, null as battery,"
    )
    sql = f"""
        select
          count(*) as active,
          {tech_cols}
          count(color) as color,
          {published} as published,
          count(*) filter (where image_urls <> '[]'::jsonb) as images,
          count(target_id) as with_target,
          count(seller_id) as with_seller
        from public.{table}
        where status in ('nuovo', 'visto')
    """
    with _get_pool().connection() as conn:
        agg = conn.execute(sql).fetchone()
        # Modello riconosciuto: la chiave di variante ha un modello vero (stessa
        # regola delle statistiche per modello).
        variants = conn.execute(
            f"select variant_key, count(*) as n from public.{table} "
            f"where status in ('nuovo','visto') group by variant_key"
        ).fetchall()
        runs = conn.execute(
            """
            select count(*) as runs,
                   count(*) filter (where status = 'down') as down,
                   coalesce(sum(requests), 0) as requests,
                   coalesce(sum(gaps), 0) as gaps,
                   coalesce(sum(new_count), 0) as new_count
            from public.scrape_runs
            where category = %s and ran_at >= now() - interval '24 hours'
            """,
            ("automobile" if not tech else "smartphone",),
        ).fetchone()
        removed_7d = conn.execute(
            f"select count(*) as n from public.{table} "
            f"where status in ('venduto_rimosso','scaduto') and updated_at >= now() - interval '7 days'"
        ).fetchone()

    active = agg["active"] or 0
    if tech:
        with_model = 0
        for row in variants:
            vk = row["variant_key"] or ""
            mk = vk.rsplit("-", 1)[0] if "-" in vk else vk
            # La chiave modello è canonica se il resolver la riconosce.
            if mk.startswith("iphone-") and iphone_model_key(mk.replace("-", " ")) == mk:
                with_model += row["n"]
    else:
        with_model = sum(r["n"] for r in variants if r["variant_key"])

    inventory = None
    try:
        rows = (
            get_db().table("app_settings").select("value")
            .eq("key", f"inventory_last:{'smartphone' if tech else 'automobile'}")
            .limit(1).execute().data
        )
        inventory = rows[0]["value"] if rows else None
    except Exception:
        inventory = None

    fields = {
        "memoria": _pct(agg["storage"], active) if tech else None,
        "batteria": _pct(agg["battery"], active) if tech else None,
        "colore": _pct(agg["color"], active),
        "dataPubblicazione": _pct(agg["published"], active) if agg["published"] is not None else None,
        "foto": _pct(agg["images"], active),
        "modelloRiconosciuto": _pct(with_model, active),
        "target": _pct(agg["with_target"], active),
        "venditore": _pct(agg["with_seller"], active),
    }
    return {
        "category": "smartphone" if tech else "automobile",
        "activeListings": active,
        "coverage": {
            "subitoTotal": (inventory or {}).get("subitoTotal"),
            "seenLastInventory": (inventory or {}).get("seen"),
            "keptLastInventory": (inventory or {}).get("kept"),
            "inventoryAt": (inventory or {}).get("at"),
            "inventoryComplete": (inventory or {}).get("complete"),
            "seenPct": _pct((inventory or {}).get("seen"), (inventory or {}).get("subitoTotal")),
        },
        "fieldsPct": {k: v for k, v in fields.items() if v is not None},
        "last24h": {
            "runs": runs["runs"], "down": runs["down"], "requests": runs["requests"],
            "gaps": runs["gaps"], "new": runs["new_count"],
        },
        "removed7d": removed_7d["n"],
    }
