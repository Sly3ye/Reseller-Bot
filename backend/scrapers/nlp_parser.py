"""Pre-parsing NLP & normalizzazione (Regex, zero dipendenze).

Analizza ``title`` + ``description`` di un annuncio e ne estrae segnale
strutturato che l'API di Subito non fornisce (o fornisce sporco):

- ``km`` / ``year``    → fallback testuale quando i campi strutturati mancano.
- ``features``         → termini chiave normalizzati (allestimenti/optional), con
                         un dizionario di sinonimi ("M Sport"/"MSport" → "M-Sport").
- ``defects_noted``    → difetti dichiarati (penalità di prezzo).
- ``urgency_flags``    → segnali di vendita urgente (leva di trattativa).
- ``exclude_from_iqr`` → True se l'auto è "incidentata"/"fuso": va tenuta fuori
                         dal calcolo della media di mercato (inquina l'IQR).

Tutto è case-insensitive e accent-insensitive dove serve.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------- estrazione km/anno

# "150.000 km", "150000km", "150 mila km", "km 150000"
_KM_RE = re.compile(
    r"(?:km[\s.:]*)?(\d{1,3}(?:[.\s]\d{3})+|\d{2,7})\s*(?:mila\s*)?k[m ]",
    re.IGNORECASE,
)
_KM_PREFIX_RE = re.compile(r"km[\s.:]*(\d{1,3}(?:[.\s]\d{3})+|\d{2,7})", re.IGNORECASE)
# Anno a 4 cifre plausibile per un'auto usata (1980–2029).
_YEAR_RE = re.compile(r"\b(19[89]\d|20[0-2]\d)\b")


# ------------------------------------------------------ dizionario di normalizzazione

# canonico → varianti che devono collassare su di esso. Il matching è su testo
# normalizzato (minuscolo, senza accenti). L'ordine non conta.
_FEATURE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "M-Sport": ("m sport", "m-sport", "msport", "pacchetto m", "pack m", "m pack"),
    "M-Performance": ("m performance", "m-performance", "m perf"),
    "Automatico": ("automatico", "automatica", "cambio automatico", "steptronic",
                   "s tronic", "s-tronic", "dsg", "tiptronic", "auto "),
    "Full-Optional": ("full optional", "full-optional", "fulloptional", "optional full",
                      "accessoriata", "tutti gli optional"),
    "Navigatore": ("navigatore", "navi ", "navigatore satellitare", "gps"),
    "Tetto-Apribile": ("tetto apribile", "tetto panoramico", "tettuccio", "sunroof"),
    "Pelle": ("interni in pelle", "sedili in pelle", "pelle totale", "full pelle"),
    "Xeno-LED": ("xeno", "xenon", "fari led", "full led", "led adattivi"),
    "Cerchi-Lega": ("cerchi in lega", "cerchi lega", "lega da"),
    "Sensori-Parcheggio": ("sensori di parcheggio", "sensori parcheggio", "park assist",
                           "telecamera posteriore", "retrocamera"),
    "Garanzia": ("garanzia", "garantita", "ancora in garanzia"),
    "Tagliandi": ("tagliandi", "tagliandata", "tagliando", "libretto tagliandi"),
    "Neopatentati": ("neopatentati", "neopatentato", "ok neopatentati"),
}

# ---------------------------------------------------------------- difetti (penalità)

# canonico → sinonimi. incidentata/fuso sono anche criterio di esclusione IQR.
_DEFECT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "frizione": ("frizione", "frizioni"),
    "graffi": ("graffi", "graffio", "graffiata", "graffiato", "rigata", "rigato"),
    "grandine": ("grandine", "grandinata"),
    "da-rivedere": ("da rivedere", "da sistemare", "da vedere", "da tagliandare"),
    "spia-motore": ("spia motore", "spia del motore", "spia accesa", "spie accese",
                    "check engine"),
    "incidentata": ("incidentata", "incidentato", "sinistrata", "sinistrato",
                    "cappottata", "urtata"),
    "fuso": ("fuso", "motore fuso", "testata", "guarnizione testata", "biella"),
}

# Difetti che squalificano l'auto dal calcolo della media di mercato.
_IQR_EXCLUSION_DEFECTS = frozenset({"incidentata", "fuso"})

# ---------------------------------------------------------------- urgenza (leva)

_URGENCY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "trasferimento": ("trasferimento", "mi trasferisco", "causa trasferimento"),
    "realizzo": ("realizzo", "realizzo causa", "svendo", "svendita"),
    "spazio": ("spazio", "far posto", "fare spazio", "non ho piu spazio"),
    "allargamento": ("allargamento", "allargamento famiglia", "famiglia che cresce"),
    "inutilizzo": ("inutilizzo", "non la uso", "poco utilizzata", "causa inutilizzo",
                   "non utilizzata"),
}


def _normalize(text: str) -> str:
    """minuscolo, senza accenti, spazi compattati (per il matching dei sinonimi)."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", stripped)


def _match_dictionary(
    haystack: str, synonyms: dict[str, tuple[str, ...]]
) -> list[str]:
    """Ritorna le chiavi canoniche i cui sinonimi compaiono nel testo normalizzato."""
    found: list[str] = []
    for canonical, variants in synonyms.items():
        if any(variant in haystack for variant in variants):
            found.append(canonical)
    return found


def _extract_km(text: str) -> int | None:
    for regex in (_KM_PREFIX_RE, _KM_RE):
        match = regex.search(text)
        if match:
            digits = re.sub(r"\D", "", match.group(1))
            if digits:
                value = int(digits)
                # "150 mila" → 150 va scalato; euristica: <1000 con "mila".
                if value < 1000 and "mila" in text.lower():
                    value *= 1000
                if 0 < value <= 1_000_000:
                    return value
    return None


def _extract_year(text: str) -> int | None:
    matches = _YEAR_RE.findall(text)
    if not matches:
        return None
    # In un titolo l'anno immatricolazione è tipicamente il più recente citato.
    return max(int(m) for m in matches)


def parse_listing(
    title: str | None, description: str | None = None
) -> dict[str, Any]:
    """Analizza titolo+descrizione e ritorna il dict di segnale strutturato.

    Chiavi: ``km``, ``year`` (int|None), ``features``, ``defects_noted``,
    ``urgency_flags`` (list[str]), ``exclude_from_iqr`` (bool).
    """
    raw = " ".join(part for part in (title, description) if part)
    norm = _normalize(raw)

    defects = _match_dictionary(norm, _DEFECT_SYNONYMS)
    return {
        "km": _extract_km(raw),
        "year": _extract_year(raw),
        "features": _match_dictionary(norm, _FEATURE_SYNONYMS),
        "defects_noted": defects,
        "urgency_flags": _match_dictionary(norm, _URGENCY_SYNONYMS),
        "exclude_from_iqr": any(d in _IQR_EXCLUSION_DEFECTS for d in defects),
    }
