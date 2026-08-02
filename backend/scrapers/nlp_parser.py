"""Pre-parsing NLP & normalizzazione (Regex, zero dipendenze).

Analizza ``title`` + ``description`` di un annuncio e ne estrae segnale
strutturato che l'API di Subito non fornisce (o fornisce sporco):

- ``km`` / ``year``    → fallback testuale quando i campi strutturati mancano.
- ``features``         → termini chiave normalizzati (allestimenti/optional auto
                         e corredo tech), con un dizionario di sinonimi
                         ("M Sport"/"MSport" → "M-Sport").
- ``defects_noted``    → difetti dichiarati (penalità di prezzo), auto e tech.
- ``urgency_flags``    → segnali di vendita urgente (leva di trattativa).
- ``storage_gb``       → taglio di memoria (64/128/256/512/1024) per il tech.
- ``battery_pct``      → salute batteria dichiarata ("batteria 87%") per il tech.
- ``exclude_from_iqr`` → True se l'annuncio va tenuto fuori dal calcolo della
                         media di mercato (auto incidentata/fusa; telefono con
                         schermo rotto, iCloud bloccato, per ricambi...).

Tutto è case-insensitive e accent-insensitive dove serve.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# ---------------------------------------------------------------- estrazione km/anno

# "150.000 km", "150000km", "150 mila km", "km 150000".
# Il lookbehind (?<![\d.]) impedisce al numero di iniziare A METÀ di un altro
# numero (es. "2018 150.000 km": senza guardia matcha "018 150.000" → valore
# assurdo che oscura il vero chilometraggio).
_KM_RE = re.compile(
    r"(?:km[\s.:]*)?(?<![\d.])(\d{1,3}(?:[.\s]\d{3})+|\d{2,7})\s*(?:mila\s*)?k[m ]",
    re.IGNORECASE,
)
_KM_PREFIX_RE = re.compile(
    r"km[\s.:]*(?<![\d.])(\d{1,3}(?:[.\s]\d{3})+|\d{2,7})", re.IGNORECASE
)
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

# ------------------------------------------------------------ difetti tech

# canonico → sinonimi (smartphone). schermo-rotto/icloud/per-ricambi sono anche
# criterio di esclusione IQR: un telefono rotto inquina la media verso il basso.
_TECH_DEFECT_SYNONYMS: dict[str, tuple[str, ...]] = {
    "schermo-rotto": ("schermo rotto", "display rotto", "vetro rotto",
                      "schermo crepato", "display crepato", "vetro crepato",
                      "vetro incrinato", "schermo incrinato", "crepa sul",
                      "schermo danneggiato", "display danneggiato"),
    "batteria-esausta": ("batteria da cambiare", "batteria da sostituire",
                         "batteria esausta", "batteria degradata",
                         "batteria ko", "batteria scarsa"),
    "icloud-bloccato": ("icloud bloccato", "blocco icloud", "blocco attivazione",
                        "account icloud attivo", "id apple bloccato"),
    "per-ricambi": ("per ricambi", "per pezzi", "pezzi di ricambio",
                    "solo ricambi", "come ricambio"),
    "da-riparare": ("da riparare", "non funzionante", "non si accende"),
    "face-id-rotto": ("face id non funziona", "face id rotto",
                      "face id non funzionante", "faceid non funziona"),
    "back-rotto": ("scocca rotta", "vetro posteriore rotto", "retro rotto",
                   "back rotto"),
}

# ----------------------------------------------------------- corredo tech

_TECH_FEATURE_SYNONYMS: dict[str, tuple[str, ...]] = {
    "Scatola": ("scatola", "box originale", "confezione originale",
                "con la sua scatola"),
    "Fattura": ("fattura", "scontrino", "prova d'acquisto", "prova di acquisto"),
    "Garanzia-Apple": ("applecare", "apple care", "garanzia apple",
                       "garanzia residua", "ancora in garanzia apple"),
    "Caricatore": ("caricatore", "caricabatterie", "cavo originale",
                   "alimentatore originale"),
    "Pari-al-Nuovo": ("pari al nuovo", "come nuovo", "come nuova",
                      "perfette condizioni", "condizioni perfette",
                      "mai caduto", "sempre con custodia", "sempre in custodia"),
    "Batteria-Cambiata": ("batteria nuova", "batteria cambiata",
                          "batteria sostituita", "batteria appena sostituita"),
}

# Difetti che squalificano l'annuncio dal calcolo della media di mercato.
_IQR_EXCLUSION_DEFECTS = frozenset({
    # auto
    "incidentata", "fuso",
    # tech: telefoni rotti/bloccati non fanno mercato del funzionante
    "schermo-rotto", "icloud-bloccato", "per-ricambi", "da-riparare",
    "batteria-esausta",
})

# Difetti "riparabili" (radar riparazioni): il margine si ricalcola al netto
# del costo di riparazione noto, vedi backend/services/scoring.py.
REPAIRABLE_DEFECTS = frozenset({"schermo-rotto", "batteria-esausta", "back-rotto"})

# ------------------------------------------------------ accessori/ricambi (tech)

# Nomi di oggetti che si vendono DA SOLI "per" un iPhone (non è il telefono).
# Il match conta solo se compaiono PRIMA di "iphone" nel titolo normalizzato:
# "Cover per iPhone 13" (accessorio in vendita) vs "iPhone 13 con cover inclusa"
# (è il telefono, l'accessorio è solo un omaggio incluso — non va escluso).
_ACCESSORY_KEYWORDS = (
    "cover", "custodia", "vetro temperato", "vetro protettivo", "vetro posteriore",
    "pellicola", "proteggi schermo", "screen protector", "caricatore",
    "caricabatterie", "cavo lightning", "cavo usb", "cavo dati", "adattatore",
    "powerbank", "auricolari", "cuffie", "airpods", "supporto auto",
    "porta cellulare", "flip cover", "custodia a libro", "retro cover",
    "guscio", "borsa porta cellulare",
)


def _is_accessory_listing(title: str | None) -> bool:
    """True se il titolo vende un ACCESSORIO/RICAMBIO "per iPhone", non il
    telefono stesso (cover, vetro, caricatore, batteria/vetro di ricambio...).

    Esclude questi annunci dal feed tech: altrimenti inquinano prezzi medi,
    valore equo e Deal Score con oggetti da pochi euro che non sono telefoni.
    """
    if not title:
        return False
    norm = _normalize(title)
    iphone_pos = norm.find("iphone")
    for kw in _ACCESSORY_KEYWORDS:
        pos = norm.find(kw)
        if pos == -1:
            continue
        if iphone_pos == -1 or pos < iphone_pos:
            return True
    return False


# ----------------------------------------------------------------- colore (tech)

# canonico → varianti (nomi commerciali Apple IT/EN). Ordine: i multi-parola e i
# più specifici prima, così "space black" vince su "black" e "deep purple" su
# "purple". Il matching prende il PRIMO canonico che compare nel testo.
_COLOR_SYNONYMS: dict[str, tuple[str, ...]] = {
    "Grafite": ("grafite", "graphite"),
    "Titanio Naturale": ("titanio naturale", "natural titanium", "titanio grezzo"),
    "Nero": ("nero siderale", "space black", "titanio nero", "black titanium",
             "mezzanotte", "midnight", "nero", "black"),
    "Bianco": ("titanio bianco", "white titanium", "galassia", "starlight",
               "bianco stellare", "bianco", "white"),
    "Argento": ("argento", "silver"),
    "Blu": ("blu pacifico", "pacific blue", "blu sierra", "sierra blue",
            "titanio blu", "blue titanium", "ultramarine", "oltremare",
            "azzurro", "blu", "blue"),
    "Verde": ("verde alpino", "alpine green", "verde notte", "midnight green",
              "verde", "green"),
    "Teal": ("teal", "verde acqua"),
    "Viola": ("deep purple", "viola intenso", "viola", "purple", "lavanda"),
    "Rosso": ("product red", "rosso", "red"),
    "Oro": ("oro", "gold", "dorato"),
    "Rosa": ("rosa", "pink"),
    "Giallo": ("giallo", "yellow"),
}


def _extract_color(norm: str) -> str | None:
    """Primo colore canonico che compare nel testo normalizzato, o None."""
    for canonical, variants in _COLOR_SYNONYMS.items():
        if any(v in norm for v in variants):
            return canonical
    return None


# ---------------------------------------------------------------- urgenza (leva)

_URGENCY_SYNONYMS: dict[str, tuple[str, ...]] = {
    "trasferimento": ("trasferimento", "mi trasferisco", "causa trasferimento"),
    "realizzo": ("realizzo", "realizzo causa", "svendo", "svendita"),
    "spazio": ("spazio", "far posto", "fare spazio", "non ho piu spazio"),
    "allargamento": ("allargamento", "allargamento famiglia", "famiglia che cresce"),
    "inutilizzo": ("inutilizzo", "non la uso", "poco utilizzata", "causa inutilizzo",
                   "non utilizzata"),
}


# ------------------------------------------------- estrazione storage/batteria

# "128GB", "128 gb", "256 giga", "1TB", "1 tb"
_STORAGE_RE = re.compile(r"\b(64|128|256|512)\s*(?:gb|giga)\b", re.IGNORECASE)
_STORAGE_TB_RE = re.compile(r"\b1\s*(?:tb|tera)\b", re.IGNORECASE)

# "batteria 87%", "batteria al 91 %", "salute batteria: 88%", "87% batteria",
# "battery health 90%". Range plausibile 50–100.
_BATTERY_RE = re.compile(
    r"(?:batteria|battery)[^%\d]{0,25}?(\d{2,3})\s*%", re.IGNORECASE
)
_BATTERY_PRE_RE = re.compile(
    r"(\d{2,3})\s*%[^\w]{0,5}(?:di\s+)?batteria", re.IGNORECASE
)


def _extract_storage_gb(text: str) -> int | None:
    if _STORAGE_TB_RE.search(text):
        return 1024
    match = _STORAGE_RE.search(text)
    return int(match.group(1)) if match else None


def _extract_battery_pct(text: str) -> int | None:
    for regex in (_BATTERY_RE, _BATTERY_PRE_RE):
        match = regex.search(text)
        if match:
            value = int(match.group(1))
            if 50 <= value <= 100:
                return value
    return None


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
    # finditer (non search): il primo match può partire "dentro" un altro
    # numero (es. l'anno in "2018 150.000 km") e produrre un valore
    # implausibile — in quel caso si prova il match successivo.
    for regex in (_KM_PREFIX_RE, _KM_RE):
        for match in regex.finditer(text):
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

    Chiavi: ``km``, ``year``, ``storage_gb``, ``battery_pct`` (int|None),
    ``features``, ``defects_noted``, ``urgency_flags`` (list[str]),
    ``exclude_from_iqr`` (bool), ``is_accessory`` (bool, dal SOLO titolo).

    Il parser è unificato auto+tech: le regex sono economiche e i dizionari
    dell'altro verticale quasi mai producono falsi positivi (un'auto non
    dichiara "iCloud bloccato", un telefono non è "grandinato").
    """
    raw = " ".join(part for part in (title, description) if part)
    norm = _normalize(raw)

    defects = _match_dictionary(norm, _DEFECT_SYNONYMS) + _match_dictionary(
        norm, _TECH_DEFECT_SYNONYMS
    )
    features = _match_dictionary(norm, _FEATURE_SYNONYMS) + _match_dictionary(
        norm, _TECH_FEATURE_SYNONYMS
    )
    # "Batteria-Cambiata" nel corredo smentisce "batteria-esausta" letta altrove
    # (es. "batteria appena sostituita" contiene... nulla di negativo, ma testi
    # tipo "batteria da cambiare? No, appena sostituita" esistono).
    if "Batteria-Cambiata" in features and "batteria-esausta" in defects:
        defects.remove("batteria-esausta")

    return {
        "km": _extract_km(raw),
        "year": _extract_year(raw),
        "storage_gb": _extract_storage_gb(raw),
        "battery_pct": _extract_battery_pct(raw),
        "color": _extract_color(norm),
        "features": features,
        "defects_noted": defects,
        "urgency_flags": _match_dictionary(norm, _URGENCY_SYNONYMS),
        "exclude_from_iqr": any(d in _IQR_EXCLUSION_DEFECTS for d in defects),
        "is_accessory": _is_accessory_listing(title),
    }
