"""Risoluzione della VARIANTE CANONICA di un annuncio (scrematura BI).

Disaccoppia *come cerchiamo* (target/query) da *come raggruppiamo per
analizzare* (variante). Il problema: la query "iPhone 13" cattura anche i
"13 Pro/mini"; qui ogni annuncio viene assegnato alla sua variante pulita, così
le medie di mercato non mescolano prezzi di modelli diversi.

- **Tech**: variante = (modello, memoria) dedotta dal titolo + storage NLP.
  Es. "iPhone 13 Pro Max 256GB" → ``iphone-13-pro-max-256``; un "iPhone 13
  128GB" → ``iphone-13-128``. Risolve l'overlap base/Pro *nell'analisi*, senza
  dover complicare la ricerca.
- **Auto**: variante = (modello, generazione) dal target (query + fascia anni).
  I target auto sono già puliti per generazione (uno per fascia d'anno), quindi
  la variante segue il target: es. ``bmw-123d-2007-2013``.

Ritorna anche la **condition tier** (come-nuovo / buono / difetti / rotto|
incidentata) per escludere i non-sani dalla media di mercato e per la UI.

Modulo di sola logica (zero dipendenze DB) → testabile in isolamento.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# --------------------------------------------------------------- condition

# Difetti che rendono l'oggetto "rotto" (fuori dal mercato del funzionante).
_TECH_BROKEN = frozenset(
    {"schermo-rotto", "icloud-bloccato", "per-ricambi", "da-riparare",
     "face-id-rotto", "back-rotto"}
)
_AUTO_BROKEN = frozenset({"incidentata", "fuso"})

# Tier considerate "sane": entrano nel calcolo della media di mercato.
HEALTHY_TIERS = frozenset({"come-nuovo", "buono"})


def condition_tier(category: str, defects: list[str] | None,
                   features: list[str] | None) -> str:
    """Fascia di condizione dai segnali NLP già estratti."""
    d = set(defects or [])
    if category == "automobile":
        if d & _AUTO_BROKEN:
            return "incidentata"
        return "difetti" if d else "buono"
    # tech
    if d & _TECH_BROKEN:
        return "rotto"
    if d:
        return "difetti"
    if "Pari-al-Nuovo" in (features or []):
        return "come-nuovo"
    return "buono"


def is_healthy(tier: str) -> bool:
    return tier in HEALTHY_TIERS


# ------------------------------------------------------------------- slug

def _slug(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", stripped).strip("-") or "na"


# ------------------------------------------------------------------ tech

# iPhone: numero (13..29) + suffisso opzionale. "16e" ha la e attaccata.
# "Air" è la linea sottile introdotta con la gen 17 (al posto del Plus): senza
# di essa un "17 Air" cadrebbe nel pool del "17" base, che vale ~200€ di più.
_IPHONE_RE = re.compile(
    r"iphone\s*(\d{2})\s*(pro\s*max|pro|plus|mini|air|e)?\b", re.IGNORECASE
)


def _storage_label(storage_gb: int | None) -> str:
    if not storage_gb:
        return "memoria n/d"
    return "1TB" if storage_gb >= 1024 else f"{storage_gb}GB"


def _iphone_variant(title: str, storage_gb: int | None) -> tuple[str, str] | None:
    match = _IPHONE_RE.search(title or "")
    if not match:
        return None
    num = match.group(1)
    raw = (match.group(2) or "").lower().replace(" ", "")
    # suffix_label è già "attaccato giusto": " Pro Max" (con spazio) oppure "e"
    # (senza spazio, per il 16e). Così il model label si compone senza aggiustare.
    suffix_slug, suffix_label = {
        "promax": ("-pro-max", " Pro Max"),
        "pro": ("-pro", " Pro"),
        "plus": ("-plus", " Plus"),
        "mini": ("-mini", " mini"),
        "air": ("-air", " Air"),
        "e": ("e", "e"),                # 16e: attaccato al numero
    }.get(raw, ("", ""))

    storage_slug = str(storage_gb) if storage_gb else "na"
    key = f"iphone-{num}{suffix_slug}-{storage_slug}"

    label = f"iPhone {num}{suffix_label} {_storage_label(storage_gb)}"
    return key, label


# ------------------------------------------------------------------ auto

def _car_variant(query: str | None,
                 strict_filters: dict[str, Any] | None) -> tuple[str, str]:
    base = _slug(query or "auto")
    mn = (strict_filters or {}).get("min_year")
    mx = (strict_filters or {}).get("max_year")
    if mn or mx:
        key = f"{base}-{mn or ''}-{mx or ''}".replace("--", "-").strip("-")
        label = f"{query} ({mn or '…'}–{mx or '…'})"
    else:
        key, label = base, (query or "Auto")
    return key, label


# --------------------------------------------------------------- resolver

def resolve_variant(
    category: str,
    title: str | None,
    metadata: dict[str, Any] | None = None,
    *,
    query: str | None = None,
    strict_filters: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assegna la variante canonica e la condition tier a un annuncio.

    Chiavi ritornate: ``variant_key``, ``variant_label``, ``condition_tier``.
    """
    meta = metadata or {}
    tier = condition_tier(category, meta.get("defects_noted"), meta.get("features"))

    if category == "automobile":
        key, label = _car_variant(query, strict_filters)
        return {"variant_key": key, "variant_label": label, "condition_tier": tier}

    # tech
    resolved = _iphone_variant(title or "", meta.get("storage_gb"))
    if resolved is None:
        # Non è un iPhone riconoscibile: ripiega sul target (o sul titolo).
        base = _slug(query or title or "altro")
        storage = meta.get("storage_gb")
        key = f"{base}-{storage}" if storage else base
        label = (query or (title or "Altro")).strip()
    else:
        key, label = resolved
    return {"variant_key": key, "variant_label": label, "condition_tier": tier}


# ------------------------------------------------------------- backfill

_TABLES = {
    "smartphone": "live_opportunities_tech",
    "automobile": "live_opportunities_auto",
}


def backfill_existing() -> dict[str, int]:
    """Popola variant_key/condition_tier sulle righe esistenti (one-time).

    Import di get_db lazy: tiene il modulo privo di dipendenze DB per i test.
    Aggiorna a gruppi (una UPDATE per combinazione variante+tier) per efficienza.
    """
    from backend.core.database import get_db  # noqa: PLC0415 (lazy by design)
    from backend.scrapers.nlp_parser import parse_listing  # noqa: PLC0415

    db = get_db()
    targets = {
        row["id"]: row
        for row in (
            db.table("target_models")
            .select("id, query, strict_filters")
            .execute()
            .data
            or []
        )
    }

    result: dict[str, int] = {}
    for category, table in _TABLES.items():
        cols = (
            "id, title, storage_gb, defects_noted, features"
            if category == "smartphone"
            else "id, title, target_id, defects_noted, features"
        )
        rows = db.table(table).select(cols).execute().data or []

        groups: dict[tuple[str, str, str | None], list[str]] = {}
        for row in rows:
            if category == "smartphone":
                res = resolve_variant(
                    category,
                    row.get("title"),
                    {
                        "storage_gb": row.get("storage_gb"),
                        "defects_noted": row.get("defects_noted"),
                        "features": row.get("features"),
                    },
                )
            else:
                t = targets.get(row.get("target_id")) or {}
                res = resolve_variant(
                    category,
                    row.get("title"),
                    {
                        "defects_noted": row.get("defects_noted"),
                        "features": row.get("features"),
                    },
                    query=t.get("query"),
                    strict_filters=t.get("strict_filters"),
                )
            # Colore dal titolo (best-effort; utile per i filtri della dashboard).
            color = parse_listing(row.get("title")).get("color")
            groups.setdefault(
                (res["variant_key"], res["condition_tier"], color), []
            ).append(row["id"])

        updated = 0
        for (vk, tier, color), ids in groups.items():
            patch = {"variant_key": vk, "condition_tier": tier}
            if color is not None:
                patch["color"] = color
            for i in range(0, len(ids), 500):
                chunk = ids[i : i + 500]
                db.table(table).update(patch).in_("id", chunk).execute()
                updated += len(chunk)
        result[table] = updated
    return result

