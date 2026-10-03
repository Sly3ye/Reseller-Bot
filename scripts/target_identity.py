"""Identità di un target: (category, query, strict_filters).

Lo stesso modello può avere più target, uno per generazione, distinti solo dai
filtri (es. "BMW 125i" 2007–2013 e 2012–2019). Vincolo nel DB: migrazione 29.
Funzioni pure, usate da seed_targets.py e merge_instances.py.
"""

from __future__ import annotations

import json


def target_key(row: dict) -> tuple[str, str, str]:
    """Chiave confrontabile: i filtri come JSON canonico (ordine delle chiavi
    irrilevante, come per l'uguaglianza jsonb di Postgres)."""
    filters = row.get("strict_filters") or {}
    if isinstance(filters, str):
        filters = json.loads(filters)
    return row["category"], row["query"], json.dumps(filters, sort_keys=True)


def match_target(src: dict, candidates: list[dict]) -> str | None:
    """id del target in ``candidates`` che corrisponde a ``src``, o None.

    1. Stessa identità completa (nome + filtri).
    2. ``src`` senza filtri (target generico, es. un PC che non ha definito le
       generazioni): ripiega sul target ATTIVO con lo stesso nome, se ce n'è
       uno solo; altrimenti il primo con quel nome. Così i suoi annunci non
       creano un doppione del modello.
    Con filtri diversi da quelli esistenti è un'altra generazione → None.
    """
    key = target_key(src)
    for c in candidates:
        if target_key(c) == key:
            return c["id"]
    if key[2] != "{}":
        return None
    same_name = [c for c in candidates if (c["category"], c["query"]) == key[:2]]
    if not same_name:
        return None
    active = [c for c in same_name if c.get("is_active")]
    return (active[0] if len(active) == 1 else same_name[0])["id"]
