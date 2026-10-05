"""Risoluzione della VARIANTE CANONICA di un annuncio (scrematura BI).

Disaccoppia *come cerchiamo* (target/query) da *come raggruppiamo per
analizzare* (variante). Il problema: la query "iPhone 13" cattura anche i
"13 Pro/mini"; qui ogni annuncio viene assegnato alla sua variante pulita, così
le medie di mercato non mescolano prezzi di modelli diversi.

- **Tech**: variante = (modello, memoria) dedotta dal titolo + storage NLP.
  Es. "iPhone 13 Pro Max 256GB" → ``iphone-13-pro-max-256``; un "iPhone 13
  128GB" → ``iphone-13-128``. Risolve l'overlap base/Pro *nell'analisi*, senza
  dover complicare la ricerca.
- **Auto**: variante = (modello, generazione) dedotta dall'annuncio con la
  tabella ``data/car_generations.json``: la sigla scritta ("F20") vince, poi
  l'anno. Es. ``bmw-125i@f2x``. Generazione incerta (anno a cavallo di due, o
  fuori tabella) → ``bmw-125i@nd``: pool a parte, mai mescolato. Annunci di un
  altro modello ("X1 23d") o di ricambi ("Motore BMW 123d") → ``…@escluso``.
  Modelli senza tabella: ripiego sul target (query + fascia anni).

Ritorna anche la **condition tier** (come-nuovo / buono / difetti / rotto|
incidentata) per escludere i non-sani dalla media di mercato e per la UI.

Modulo di sola logica (zero dipendenze DB) → testabile in isolamento.
"""

from __future__ import annotations

import json
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

# --------------------------------------------------------------- condition

# Difetti che rendono l'oggetto "rotto" (fuori dal mercato del funzionante).
# I tre "a rischio" (scheda madre, acqua, non si accende) sono rotti anche loro.
_TECH_BROKEN = frozenset(
    {"schermo-rotto", "icloud-bloccato", "per-ricambi", "da-riparare",
     "face-id-rotto", "back-rotto", "scheda-madre", "acqua", "non-si-accende"}
)
# Codici del dizionario AUTO: il parser è unico, quindi in un annuncio iPhone
# "fuso orario" o "da rivedere" li farebbero scattare. Per il tech non contano.
AUTO_ONLY_DEFECTS = frozenset(
    {"frizione", "grandine", "da-rivedere", "spia-motore", "incidentata", "fuso"}
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
    d -= AUTO_ONLY_DEFECTS
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


_IPHONE_WORD_RE = re.compile(r"iphone", re.IGNORECASE)


def model_text(title: str | None, description: str | None = None) -> str:
    """Testo da cui leggere il MODELLO di un annuncio: il titolo, oppure, se il
    titolo dice solo "iPhone" ("Iphone", "Telefono iPhone"), il modello scritto
    nella descrizione ("Vendo iPhone 12 Pro 128GB...") come etichetta canonica
    ("iPhone 12 Pro").

    La descrizione vale solo se nomina UN modello: "passaggio al 16, vendo il
    mio iPhone 13" o i lotti restano senza modello (meglio nessuno che uno
    sbagliato). Gli accessori ("Cover per iPhone") restano sul titolo.
    """
    title = title or ""
    if iphone_model_key(title) or not description or not mentions_iphone(title):
        return title
    from backend.scrapers.nlp_parser import _is_accessory_listing  # noqa: PLC0415 (import circolare)

    if _is_accessory_listing(title):
        return title
    text = normalize_iphone(description)
    models = {}
    for m in _IPHONE_WORD_RE.finditer(text):
        model = _iphone_model(text[m.start(): m.start() + 40])
        if model:
            models[f"iphone-{model[0]}{model[1]}"] = model
    if len(models) != 1:
        return title
    num, _, label = next(iter(models.values()))
    return f"iPhone {num}{label}" if num else f"iPhone {label}"


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

# Separatore modello@generazione: la chiave modello di un'auto è tutto ciò che
# precede "@" (prima "bmw-123d" diventava "bmw" togliendo l'ultimo segmento,
# regola pensata per la memoria degli iPhone).
CAR_GEN_SEP = "@"
CAR_GEN_UNKNOWN = "nd"
CAR_EXCLUDED = "escluso"


@lru_cache(maxsize=1)
def _car_table() -> dict[str, Any]:
    path = Path(__file__).resolve().parents[1] / "data" / "car_generations.json"
    if not path.exists():
        return {"models": {}, "parts_prefix": []}
    return json.loads(path.read_text(encoding="utf-8"))


def car_model_label(model_slug: str) -> str | None:
    """Nome leggibile del modello auto ("bmw-125i" → "BMW 125i"), se in tabella."""
    return (_car_table()["models"].get(model_slug) or {}).get("label")


def car_generation(model_slug: str, year: int | None, text: str) -> tuple[str, str] | None:
    """(codice, etichetta) della generazione, CAR_GEN_UNKNOWN se incerta, None
    se il modello non è in tabella. ``text`` = titolo (+ descrizione)."""
    model = _car_table()["models"].get(model_slug)
    if not model:
        return None
    gens = model["generations"]
    low = text.lower()
    named = [g for g in gens if any(re.search(rf"\b{c}\b", low) for c in g.get("codes", []))]
    if len(named) == 1:
        return named[0]["code"], named[0]["label"]
    by_year = [g for g in gens if year and g["from"] <= int(year) <= g["to"]]
    if len(by_year) == 1:
        return by_year[0]["code"], by_year[0]["label"]
    return CAR_GEN_UNKNOWN, "generazione incerta"


def car_generation_years(variant_key: str | None) -> tuple[int, int] | None:
    """Anni (da, a) della generazione di una variante auto ``modello@codice``,
    o None se non in tabella / incerta."""
    if not variant_key or CAR_GEN_SEP not in variant_key:
        return None
    model_slug, code = variant_key.split(CAR_GEN_SEP, 1)
    for g in (_car_table()["models"].get(model_slug) or {}).get("generations", []):
        if g["code"] == code:
            return g["from"], g["to"]
    return None


def car_generation_label(variant_key: str | None) -> str | None:
    """Etichetta della generazione di una variante auto ("F20/F21"), o None."""
    if not variant_key or CAR_GEN_SEP not in variant_key:
        return None
    model_slug, code = variant_key.split(CAR_GEN_SEP, 1)
    if code == CAR_GEN_UNKNOWN:
        return "generazione incerta"
    if code == CAR_EXCLUDED:
        return "altro modello / ricambio"
    for g in (_car_table()["models"].get(model_slug) or {}).get("generations", []):
        if g["code"] == code:
            return g["label"]
    return code


def year_fits_generation(variant_key: str | None, year: int | None) -> bool:
    """L'anno dichiarato è plausibile per la generazione (±1 per immatricolazioni
    tardive)? Un "125i F20 del 2025" ha un anno sbagliato: niente stima."""
    years = car_generation_years(variant_key)
    if years is None or not year:
        return years is None
    return years[0] - 1 <= int(year) <= years[1] + 1


def _car_excluded(model_slug: str, title: str, km: int | None = None) -> bool:
    """Titolo di un altro modello ("Bmw X1 123d") o di un ricambio ("Motore
    BMW 123D", "Kat. 200 celle ... 125i f20"): non è l'auto cercata e non deve
    entrare nei prezzi. Senza km dichiarati basta una parola da ricambio in
    qualunque punto del titolo."""
    table = _car_table()
    low = _slug(title).replace("-", " ")
    words = low.split()
    if words and words[0] in table.get("parts_prefix", []):
        return True
    if km is None and set(words) & set(table.get("parts_anywhere_without_km", [])):
        return True
    model = table["models"].get(model_slug) or {}
    return any(re.search(rf"\b{re.escape(w)}\b", low) for w in model.get("exclude", []))


def _car_variant(query: str | None,
                 strict_filters: dict[str, Any] | None,
                 title: str | None = None,
                 year: int | None = None,
                 description: str | None = None,
                 km: int | None = None) -> tuple[str, str]:
    base = _slug(query or "auto")
    label_base = car_model_label(base) or (query or "Auto")
    if title is not None and car_model_label(base):
        if _car_excluded(base, title, km):
            return f"{base}{CAR_GEN_SEP}{CAR_EXCLUDED}", f"{label_base} (altro modello o ricambio)"
        code, gen_label = car_generation(base, year, f"{title} {description or ''}")
        return f"{base}{CAR_GEN_SEP}{code}", f"{label_base} {gen_label}"
    # Modello senza tabella: la generazione la dà il target, se ha la fascia anni.
    mn = (strict_filters or {}).get("min_year")
    mx = (strict_filters or {}).get("max_year")
    if mn or mx:
        key = f"{base}{CAR_GEN_SEP}{mn or ''}-{mx or ''}"
        label = f"{label_base} ({mn or '…'}–{mx or '…'})"
    else:
        key, label = base, label_base
    return key, label


# --------------------------------------------------------------- resolver

def resolve_variant(
    category: str,
    title: str | None,
    metadata: dict[str, Any] | None = None,
    *,
    query: str | None = None,
    strict_filters: dict[str, Any] | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Assegna la variante canonica e la condition tier a un annuncio.

    Chiavi ritornate: ``variant_key``, ``variant_label``, ``condition_tier``.
    Con la ``description`` il modello si legge anche da lì quando il titolo
    non lo dice (vedi ``model_text``).
    """
    meta = metadata or {}
    tier = condition_tier(category, meta.get("defects_noted"), meta.get("features"))

    if category == "automobile":
        key, label = _car_variant(query, strict_filters, title, meta.get("year"), description,
                                  meta.get("km"))
        return {"variant_key": key, "variant_label": label, "condition_tier": tier}

    # tech
    resolved = _iphone_variant(model_text(title, description), meta.get("storage_gb"))
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

