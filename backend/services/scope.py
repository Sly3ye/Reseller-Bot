"""Ambito iPhone: fuori dalla tabella degli annunci ciò che non trattiamo.

Il 5/10 l'ambito torna "iPhone 12 e successivi" (``IPHONE_MIN_GEN``): sotto
c'è poco giro e poco margine. Fuori anche accessori e altri marchi rimasti
dallo storico (``nlp_parser._is_accessory_listing``). Raccolta e feed li
scartano già; qui si spostano quelli già raccolti nell'archivio (migrazione
28) invece di cancellarli: feed, statistiche, inventario, foto e AI lavorano
solo sull'ambito, e se l'ambito cambia ``restore`` li rimette al loro posto.

Lo spostamento salta i trigger di listing_events (session_replication_role):
non sono "doppioni fusi" e non devono comparire come tali nella storia.
Gli annunci col modello NON riconosciuto restano: li legge l'AI.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

TABLE = "live_opportunities_tech"
ARCHIVE = "live_opportunities_tech_archivio"
REASON_OLD = "sotto_ambito"
REASON_NOT_IPHONE = "non_iphone"


def classify(variant_key: str | None, title: str | None) -> str | None:
    """Motivo per cui l'annuncio è fuori ambito, o None se resta."""
    from backend.scrapers.nlp_parser import _is_accessory_listing  # noqa: PLC0415
    from backend.services.reads import _model_key  # noqa: PLC0415
    from backend.services.variants import in_iphone_scope  # noqa: PLC0415

    if _is_accessory_listing(title):
        return REASON_NOT_IPHONE
    if in_iphone_scope(_model_key(variant_key)) is False:
        return REASON_OLD
    return None


def _columns(conn: Any) -> list[str]:
    rows = conn.execute(
        "select column_name from information_schema.columns "
        "where table_schema = 'public' and table_name = %s order by ordinal_position",
        (TABLE,),
    ).fetchall()
    return [r["column_name"] for r in rows]


def archive_out_of_scope(apply: bool = False) -> dict[str, Any]:
    """Conta (e con ``apply`` sposta) gli annunci fuori ambito, di ogni stato."""
    from backend.core.database import _get_pool, has_column  # noqa: PLC0415

    if not has_column(ARCHIVE, "archived_reason"):
        return {"error": "manca la migrazione 28"}
    with _get_pool().connection() as conn:
        rows = conn.execute(f"select id::text as id, variant_key, title from public.{TABLE}").fetchall()
        by_reason: dict[str, list[str]] = {}
        for r in rows:
            reason = classify(r["variant_key"], r["title"])
            if reason:
                by_reason.setdefault(reason, []).append(r["id"])
        counts = {reason: len(ids) for reason, ids in by_reason.items()}
        if not apply or not by_reason:
            return {"applied": False, "total": len(rows), "out": counts}
        cols = _columns(conn)
        col_list = ", ".join(f'"{c}"' for c in cols)
        with conn.transaction():
            # Niente trigger durante lo spostamento: non sono doppioni fusi.
            conn.execute("set local session_replication_role = replica")
            for reason, ids in by_reason.items():
                conn.execute(
                    f"insert into public.{ARCHIVE} ({col_list}, archived_reason) "
                    f"select {col_list}, %s from public.{TABLE} where id = any(%s::uuid[]) "
                    f"on conflict (id) do nothing",
                    (reason, ids),
                )
                conn.execute(f"delete from public.{TABLE} where id = any(%s::uuid[])", (ids,))
    moved = {i for ids in by_reason.values() for i in ids}
    _prune_verify_queue(moved)
    logger.info("Ambito iPhone: spostati in archivio %s", counts)
    return {"applied": True, "total": len(rows), "out": counts}


def restore(reason: str | None = None) -> int:
    """Rimette nella tabella degli annunci quelli archiviati (tutti o per motivo)."""
    from backend.core.database import _get_pool  # noqa: PLC0415

    with _get_pool().connection() as conn:
        cols = _columns(conn)
        col_list = ", ".join(f'"{c}"' for c in cols)
        where = "where archived_reason = %s" if reason else ""
        params = (reason,) if reason else ()
        with conn.transaction():
            conn.execute("set local session_replication_role = replica")
            cur = conn.execute(
                f"insert into public.{TABLE} ({col_list}) select {col_list} from public.{ARCHIVE} {where} "
                f"on conflict do nothing",
                params,
            )
            restored = cur.rowcount
            conn.execute(f"delete from public.{ARCHIVE} {where}", params)
    return restored


def _prune_verify_queue(moved: set[str]) -> None:
    """Le verifiche dei venduti in coda non servono più per gli archiviati."""
    from backend.core.database import get_db  # noqa: PLC0415
    from backend.services.sweep import _load_state, _save_state, _verify_queue_key  # noqa: PLC0415

    db = get_db()
    key = _verify_queue_key("smartphone")
    state = _load_state(db, key)
    items = state.get("items") or []
    kept = [it for it in items if it["id"] not in moved]
    if len(kept) != len(items):
        state["items"] = kept
        _save_state(db, key, state)
        logger.info("Coda verifiche: tolti %d annunci fuori ambito", len(items) - len(kept))
