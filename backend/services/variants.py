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
# I tre "a rischio" (scheda madre, acqua, non si accende) sono rotti anche loro.
_TECH_BROKEN = frozenset(
    {"schermo-rotto", "icloud-bloccato", "per-ricambi", "da-riparare",
     "face-id-rotto", "back-rotto", "scheda-madre", "acqua", "non-si-accende"}
)
# Solo estetici: un telefono con qualche graffio è il normale mercato dell'usato
# e deve restare nel pool dei sani che fa il prezzo (prima finiva in "difetti").
_TECH_COSMETIC = frozenset({"graffi"})
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
    if d - _TECH_COSMETIC:
        return "difetti"  # guasto funzionale riparabile (batteria, fotocamera, audio...)
    if "Pari-al-Nuovo" in (features or []) and not d:
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

# iPhone: numero (6..29, con la "s" dei 6s/5s) + suffisso opzionale. "16e" ha
# la e attaccata. "Air" è la linea sottile introdotta con la gen 17 (al posto
# del Plus): senza, un "17 Air" cadrebbe nel pool del "17" base (~200€ in più).
# Il \b finale evita che "iphone 128gb" diventi un "iPhone 12".
# La lettera dopo il numero (6s, 5c, 16e) è un gruppo a sé. Attaccata vale
# sempre; staccata solo la "e" e solo se dopo c'è fine titolo, un numero o
# punteggiatura: "iPhone 16 e 128GB" è un 16e (si scrive spesso così), mentre
# in "iPhone 12 e cover" / "iPhone 16 e custodia" la "e" è una congiunzione.
_IPHONE_RE = re.compile(
    r"iphone\s*(\d{1,2})([sce]|\s+e(?=\s*$|\s*\d|\s*[^\w\s]))?\s*(pro\s*max|pro|plus|mini|air)?\b",
    re.IGNORECASE,
)
# Modelli più vecchi della gen 11 effettivamente esistiti (numero+lettera, suffisso).
_OLD_IPHONES = frozenset({
    ("4", ""), ("4s", ""), ("5", ""), ("5c", ""), ("5s", ""),
    ("6", ""), ("6", "plus"), ("6s", ""), ("6s", "plus"),
    ("7", ""), ("7", "plus"), ("8", ""), ("8", "plus"),
})
# Generazione più alta accettata: alzala quando esce la successiva (oltre,
# "iPhone 27 Pro Max" è un refuso, non un modello).
MAX_IPHONE_GEN = 19


def _is_real_iphone(num: str, suffix: str) -> bool:
    """La combinazione (numero[lettera], suffisso) è un modello Apple esistito?
    Dalla gen 11: base/Pro/Pro Max sempre; mini solo 12-13; Plus solo 14-16;
    "e" (modello economico) dalla 16."""
    if num[-1:].isalpha():
        gen, letter = int(num[:-1]), num[-1]
    else:
        gen, letter = int(num), ""
    if gen < 11:
        return (num, suffix) in _OLD_IPHONES
    if gen > MAX_IPHONE_GEN or letter in ("s", "c"):
        return False
    if letter == "e":
        return gen >= 16 and suffix == ""
    if suffix in ("", "pro", "promax"):
        return True
    if suffix == "mini":
        return gen in (12, 13)
    if suffix == "plus":
        return 14 <= gen <= 16
    return False
# Modelli a lettere (2017-2022): X, XR, XS, XS Max, SE. Nei titoli reali l'XS
# Max è spesso "XS Pro Max" (che non esiste) e il primo SE "iPhone 5 SE".
_IPHONE_LETTER_RE = re.compile(
    r"iphone\s*(?:5\s*)?(xs\s*(?:pro\s*)?max|xr|xs|x|se)\b", re.IGNORECASE
)
_LETTER_MODELS = {
    "xsmax": ("xs-max", "XS Max"),
    "xspromax": ("xs-max", "XS Max"),
    "xr": ("xr", "XR"),
    "xs": ("xs", "XS"),
    "x": ("x", "X"),
    "se": ("se", "SE"),
}


def _storage_label(storage_gb: int | None) -> str:
    if not storage_gb:
        return "memoria n/d"
    return "1TB" if storage_gb >= 1024 else f"{storage_gb}GB"


# suffix_label è già "attaccato giusto": " Pro Max" (con spazio) oppure "e"
# (senza spazio, per il 16e). Così il model label si compone senza aggiustare.
_IPHONE_SUFFIX = {
    "promax": ("-pro-max", " Pro Max"),
    "pro": ("-pro", " Pro"),
    "plus": ("-plus", " Plus"),
    "mini": ("-mini", " mini"),
    "air": ("-air", " Air"),
}


# Refusi frequenti nei titoli reali ("I phone 16 pro", "Iphon 13", "Iphome 17").
_IPHONE_TYPO_RE = re.compile(r"\b(?:i\s?-?\s?phone|iphon|iphome|ipohne|iphne)(?=\b|\d)", re.IGNORECASE)
# L'Air (2025) si vende come "iPhone Air", senza numero di generazione.
_IPHONE_AIR_RE = re.compile(r"iphone\s*(?:\d{2}\s*)?air\b", re.IGNORECASE)


def normalize_iphone(text: str | None) -> str:
    """Riporta i refusi a "iphone" (il resto del testo resta com'è)."""
    return _IPHONE_TYPO_RE.sub("iphone", text or "")


def mentions_iphone(title: str | None) -> bool:
    return "iphone" in normalize_iphone(title).lower()


def _iphone_model(title: str) -> tuple[str, str, str] | None:
    """(numero, suffix_slug, suffix_label) del primo iPhone nel testo.

    L'Air è un modello a sé (``iphone-air``) che lo si scriva "iPhone Air" o
    "iPhone 17 Air": senza, gli annunci "iPhone Air" non avevano modello. I
    modelli a lettere tornano come numero vuoto + slug ("", "xs-max", "XS Max").
    Se nel testo compaiono più modelli vince il primo."""
    text = normalize_iphone(title)
    if _IPHONE_AIR_RE.search(text):
        return "", "air", "Air"
    numeric = _IPHONE_RE.search(text)
    letter = _IPHONE_LETTER_RE.search(text)
    if letter and (numeric is None or letter.start() <= numeric.start()):
        slug, label = _LETTER_MODELS[letter.group(1).lower().replace(" ", "")]
        return "", slug, label
    if numeric is None:
        return None
    num = numeric.group(1) + (numeric.group(2) or "").strip().lower()
    raw = (numeric.group(3) or "").lower().replace(" ", "")
    if not _is_real_iphone(num, raw):
        # "iPhone 1 Pro", "iPhone 17 mini", "iPhone 27": refuso o falso, non
        # un modello. Meglio nessun modello che un modello inventato.
        return None
    suffix_slug, suffix_label = _IPHONE_SUFFIX.get(raw, ("", ""))
    return num, suffix_slug, suffix_label


def iphone_model_key(text: str | None) -> str | None:
    """Chiave di MODELLO senza memoria: "iPhone 13 Pro 256GB" → "iphone-13-pro",
    "iPhone XS Max" → "iphone-xs-max", "iPhone Air" → "iphone-air".

    Vale sia per un titolo sia per la query di un target, ed è ciò che lega un
    annuncio trovato da una ricerca ampia al target del suo modello.
    """
    model = _iphone_model(text or "")
    if model is None:
        return None
    num, suffix_slug, _ = model
    return f"iphone-{num}{suffix_slug}"


def _iphone_variant(title: str, storage_gb: int | None) -> tuple[str, str] | None:
    model = _iphone_model(title)
    if model is None:
        return None
    num, suffix_slug, suffix_label = model

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

