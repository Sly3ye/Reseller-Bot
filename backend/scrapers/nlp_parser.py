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
    # Lavori e storia che spostano davvero il prezzo di un'auto usata.
    "Distribuzione-Fatta": ("distribuzione fatta", "distribuzione appena fatta", "distribuzione nuova",
                            "catena distribuzione fatta", "catena di distribuzione fatta",
                            "catena distribuzione nuova", "catena cambiata", "catena sostituita",
                            "kit distribuzione", "cinghia fatta", "cinghia di distribuzione fatta"),
    "Tagliandi-Certificati": ("tagliandi certificati", "tagliandi bmw", "tagliandi ufficiali",
                              "tagliandi documentati", "storico tagliandi", "service bmw",
                              "tagliandi in concessionaria", "fatture dei tagliandi"),
    "Unico-Proprietario": ("unico proprietario", "un solo proprietario", "primo proprietario",
                           "1 proprietario", "prima mano"),
    "Revisione-Fatta": ("revisione fatta", "revisionata", "revisione appena fatta", "revisione nuova",
                        "revisione valida", "revisione fino"),
    "Gancio-Traino": ("gancio traino", "gancio di traino"),
    "GPL-Metano": ("impianto gpl", "a gpl", "gpl ", "metano", "bombola"),
}

# ---------------------------------------------------------------- difetti (penalità)

# canonico → sinonimi. incidentata/fuso sono anche criterio di esclusione IQR.
_DEFECT_SYNONYMS: dict[str, tuple[str, ...]] = {
    # Solo la frizione DA FARE: "frizione nuova/fatta/rifatta" è un pregio (9 su 9
    # dei "frizione" segnati il 2026-10-05 erano lavori già fatti).
    "frizione": ("frizione da sostituire", "frizione da cambiare", "frizione da fare",
                 "frizione da rifare", "frizione slitta", "frizione che slitta",
                 "frizione andata", "frizione bruciata", "frizione consumata",
                 "problema alla frizione", "problemi alla frizione", "problema frizione"),
    "graffi": ("graffi", "graffio", "graffiata", "graffiato", "rigata", "rigato"),
    "grandine": ("grandine", "grandinata"),
    # "da vedere" no: "Pronta da vedere e provare" è un invito, non un difetto.
    "da-rivedere": ("da rivedere", "da sistemare", "da tagliandare"),
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
    # accessori
    "cover", "custodia", "vetro temperato", "vetro protettivo", "vetro posteriore",
    "pellicola", "proteggi schermo", "screen protector", "caricatore",
    "caricabatterie", "cavo lightning", "cavo usb", "cavo dati", "adattatore",
    "powerbank", "auricolari", "cuffie", "airpods", "supporto auto",
    "porta cellulare", "flip cover", "custodia a libro", "retro cover",
    "guscio", "borsa porta cellulare",
    # visti passare il 5/10 come "affari" da migliaia di euro: "MOFT Kit per
    # iPhone", "Portafoglio MagSafe per iPhone", "2 Custodie iPhone", "Master
    # Grip per iPhone", "Batteria originale Apple per iPhone", "Mini iPhone
    # 17 Pro Max" (giocattolo: il modello "mini" si scrive DOPO "iphone")
    "custodie", "kit", "portafoglio", "magsafe", "grip", "supporto",
    "gimbal", "stabilizzatore", "batteria originale", "batteria compatibile",
    "batteria di ricambio", "mini",
    # scatole vuote, controller da gioco
    "scatola", "scatole", "box originale", "controller", "backbone",
    # altri marchi PRIMA di "iphone" ("Samsung S26 Ultra ... iPhone"): non sono
    # iPhone (comparto a parte, se mai). Dopo ("iPhone 13 o scambio Samsung")
    # resta un iPhone.
    "samsung", "galaxy", "xiaomi", "redmi", "huawei", "oppo", "realme", "motorola",
    "google pixel", "pixel", "oneplus", "honor", "nokia", "poco",
    # memorie esterne "per iPhone" (SSD/chiavette): non sono telefoni
    "ssd", "flashpod", "chiavetta", "hard disk", "memoria esterna",
    # ricambi (pezzi singoli): stessa regola posizionale — "Display iPhone 15"
    # è un ricambio, "iPhone 15 display rotto" è un telefono col display rotto.
    "display", "schermo", "lcd", "oled", "touch screen", "scocca", "carcassa",
    "telaio", "scheda madre", "fotocamera", "fotocamere", "altoparlante",
    "connettore", "flat", "vibrazione", "antenna", "tasto accensione",
    "vetro fotocamera", "lente fotocamera", "ricambio", "ricambi",
)


# Match su confini di parola: senza \b "oled" scatterebbe dentro "AMOLED"
# (Garmin) e "cover" dentro "discover".
_ACCESSORY_RE = re.compile(
    r"\b(?:" + "|".join(re.escape(kw) for kw in _ACCESSORY_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


def _is_accessory_listing(title: str | None) -> bool:
    """True se il titolo vende un ACCESSORIO/RICAMBIO "per iPhone", non il
    telefono stesso (cover, vetro, caricatore, display/scocca di ricambio...).

    Regola posizionale: conta solo se la parola-accessorio precede "iphone".
    "Display iPhone 15" è un ricambio; "iPhone 15 display rotto" è un telefono
    col display rotto (che vogliamo tenere, col suo malus di condizione).

    Esclude questi annunci dal feed tech: altrimenti inquinano prezzi medi,
    valore equo e Deal Score con oggetti che non sono telefoni.
    """
    if not title:
        return False
    from backend.services.variants import normalize_iphone  # noqa: PLC0415 (import circolare)

    # Refusi riportati a "iphone" prima di confrontare le posizioni: "I-phone
    # 12 mini" e "Iphon 13 mini" sono telefoni, non accessori senza iPhone.
    norm = normalize_iphone(_normalize(title))
    if _is_fake(norm):
        return True
    match = _ACCESSORY_RE.search(norm)
    if match is None:
        return False
    iphone_pos = norm.find("iphone")
    return iphone_pos == -1 or match.start() < iphone_pos


# Cloni e repliche dichiarati nel titolo, in qualunque posizione ("iphone 17
# promax 2 Tb clone"): non sono iPhone. Salvo la negazione subito prima ("non
# è una replica", "no clone"), che invece rassicura su un telefono vero.
_FAKE_RE = re.compile(r"\b(?:clone|clonato|replica|fake|imitazione)\b")
_FAKE_NEGATION_RE = re.compile(r"\b(?:non|no|nessun\w*|niente)\b[^.!?,;]{0,12}$")


def _is_fake(norm: str) -> bool:
    match = _FAKE_RE.search(norm)
    return match is not None and not _FAKE_NEGATION_RE.search(norm[:match.start()])


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

# Memoria, in ordine di affidabilità (vince la prima regola che trova qualcosa,
# cercando prima nel titolo e poi nella descrizione):
# 1. con unità, anche scritta male: "128GB", "128 gb", "256 g", "64g",
#    "512Gg", "128. Gb.", "256 giga", "1TB", "1 T", "2 tera";
# 2. con parola chiave: "memoria 128", "capacità: 256", "128 di memoria";
# 3. numero nudo nel SOLO titolo ("iPhone 12 Pro 128"), mai se è un prezzo
#    ("128€", "€ 256", "256 euro") o una percentuale. 16/32 nudi no: troppo
#    ambigui (età, quantità).
_GB_VALUES = r"(16|32|64|128|256|512)"
_STORAGE_RE = re.compile(
    _GB_VALUES + r"\s*[.,]?\s*(?:g\s*\.?\s*b\b|gig\w*|gbyte\w*|gg?\b)"
    # "256 MB": refuso per GB (nessun iPhone ha 64–512 MB di memoria)
    r"|\b(64|128|256|512)\s*mb\b"
    # unità prima: "GB 128", "gb:256"
    r"|\bg\s*b\s*[:.=]?\s*(16|32|64|128|256|512)\b(?!\s*[%€])",
    re.IGNORECASE,
)
_STORAGE_TB_RE = re.compile(r"\b([12])\s*[.,]?\s*(?:tb\b|t\s*\.?\s*b\b|tera\w*|t\b)", re.IGNORECASE)
_STORAGE_1000_RE = re.compile(r"\b1000\s*(?:gb|g\b|gig\w*)", re.IGNORECASE)
# Numero nudo subito dopo il modello, anche in descrizione: "iphone 14 128 in
# ottime", "iPhone 15 pro max 256, sempre...". Il prezzo resta escluso.
_STORAGE_AFTER_MODEL_RE = re.compile(
    r"iphone\s*(?:\d{1,2}|x[rs]?|se)\s*(?:pro\s*max|promax|pro|plus|mini|max)?\s*[,\-–:]?\s*"
    r"(64|128|256|512)\b(?![.,]\d)(?!\s*(?:€|\$|%|eur|euro|e\b|,-|\.-))",
    re.IGNORECASE,
)
_STORAGE_KEYWORD_RE = re.compile(
    r"(?:memoria|capacit[aà]|storage|archiviazione|spazio|rom)\W{0,3}"
    r"(?:interna\W{0,3})?(?:(?:di|da)\W{1,3})?" + _GB_VALUES + r"\b(?!\s*[%€])"
    r"|\b" + _GB_VALUES + r"\s+(?:di\s+)?(?:memoria|spazio)\b",
    re.IGNORECASE,
)
_STORAGE_BARE_RE = re.compile(
    r"(?<![€$\d.,])(?<!€\s)\b(64|128|256|512)\b(?![.,]\d)(?!\s*(?:€|\$|%|eur|euro|e\b|,-|\.-))",
    re.IGNORECASE,
)

# "batteria 87%", "batteria al 91 %", "salute batteria: 88%", "87% batteria",
# "battery health 90%". Range plausibile 50–100.
_BATTERY_RE = re.compile(
    r"(?:batteria|battery)[^%\d]{0,25}?(\d{2,3})\s*%", re.IGNORECASE
)
_BATTERY_PRE_RE = re.compile(
    r"(\d{2,3})\s*%[^\w]{0,5}(?:di\s+)?batteria", re.IGNORECASE
)


def _storage_with_unit(text: str) -> int | None:
    """Prima memoria con unità nel testo (GB o TB, vince la più a sinistra)."""
    hits = []
    for m in _STORAGE_RE.finditer(text):
        # "\b" a sinistra a mano: "iPhone12 128GB" va, "2128GB" no.
        if m.start() == 0 or not text[m.start() - 1].isdigit():
            hits.append((m.start(), int(next(g for g in m.groups() if g))))
            break
    if m := _STORAGE_TB_RE.search(text):
        hits.append((m.start(), 1024 * int(m.group(1))))
    if m := _STORAGE_1000_RE.search(text):
        hits.append((m.start(), 1024))
    return min(hits)[1] if hits else None


def _extract_storage_gb(title: str | None, description: str | None = None) -> int | None:
    parts = [p for p in (title, description) if p]
    for text in parts:
        if (gb := _storage_with_unit(text)) is not None:
            return gb
    for text in parts:
        if m := _STORAGE_KEYWORD_RE.search(text):
            return int(m.group(1) or m.group(2))
    if title and (m := _STORAGE_BARE_RE.search(title)):
        return int(m.group(1))
    from backend.services.variants import normalize_iphone  # noqa: PLC0415 (evita import circolari)

    if description and (m := _STORAGE_AFTER_MODEL_RE.search(normalize_iphone(description))):
        return int(m.group(1))
    return None


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


# Negazione nelle parole immediatamente prima ("nessun graffio", "senza crepe",
# "non presenta segni", "no blocco iCloud"). Si guarda solo dentro la stessa
# frase: un punto o un a-capo chiude il contesto.
_NEGATION_RE = re.compile(
    r"\b(?:senza|nessun[oa]?|neanche|nemmeno|neppure|zero|privo|priva|esente|"
    r"non\s+(?:ha|ho|presenta|ci\s+sono|c\s?e|ha\s+mai)|mai|no)\b([^.!?\n]{0,25})$"
)
# Dopo questi la negazione non vale più: "nessun difetto, unico problema lo
# schermo crepato", "senza graffi ma con la scocca rotta".
_NEGATION_STOP_RE = re.compile(r"\b(?:ma|pero|unico|unica|tranne|salvo|eccetto|solo|solamente)\b")


def _negated(haystack: str, start: int) -> bool:
    window = haystack[max(0, start - 40):start]
    cut = max(window.rfind(c) for c in ".!?\n")
    if cut >= 0:
        window = window[cut + 1:]
    match = _NEGATION_RE.search(window)
    return bool(match) and not _NEGATION_STOP_RE.search(match.group(1))


# Dentro il tratto "parte … stato": una negazione ("display senza crepe"), un
# contrasto ("schermo perfetto, ma non funziona il Face ID") o un accessorio
# ("pellicola rotta") fanno cadere il match.
_SPAN_REJECT_RE = re.compile(
    r"\b(?:senza|nessun\w*|neanche|nemmeno|zero|privo|priva|non presenta|non ha|mai|"
    r"ma|pero|pellicol\w*|cover|custodia|vetro temperato|vetrino protett\w*)\b"
)


def _match_dictionary(
    haystack: str, synonyms: dict[str, tuple[str, ...]]
) -> list[str]:
    """Chiavi canoniche con almeno un sinonimo presente e NON negato
    ("nessun graffio" non è un graffio)."""
    found: list[str] = []
    for canonical, variants in synonyms.items():
        hit = False
        for variant in variants:
            start = haystack.find(variant)
            while start != -1 and not hit:
                if not _negated(haystack, start):
                    hit = True
                start = haystack.find(variant, start + 1)
            if hit:
                break
        if hit:
            found.append(canonical)
    return found


# --------------------------------------------- guasti tech v2 (tassonomia B3)
#
# Pattern con contesto (parte + stato) invece di frasi fisse: gli annunci reali
# scrivono "display presenta lesioni", "lo schermo è un po' crepato", "FACE ID
# NON FUNZIONATE". Ogni match passa dal controllo negazione, salvo quelli dove
# la negazione È il guasto ("senza scheda madre"). Codici = defects_noted
# storici + nuovi (vedi services/defects.py per la tassonomia).
_BREAK = r"[^.!?\n]"
_TECH_PATTERNS: dict[str, tuple[tuple[str, bool], ...]] = {
    # (regex, rispetta_negazione)
    "schermo-rotto": (
        (rf"\b(?:schermo|schemo|scermo|display|lcd|touch(?:screen)?|vetro anteriore|vetrino anteriore)"
         rf"{_BREAK}{{0,30}}"
         r"(?:rott|crepat|crepe|crepa\b|incrinat|danneggiat|lesion|non (?:\w+ )?funzion|righe|riga\b|linee|"
         r"striscia|strisce|pixel|macchi|da sostituire|da cambiare|alzat)", True),
        (rf"\b(?:rott|crepat|incrinat|lesion|alzat|strisci|righ|riga|linee|macchi)\w*{_BREAK}{{0,15}}"
         r"\b(?:schermo|display|vetro anteriore)", True),
        (r"\blesion\w* (?:del|sul|sullo|nel) (?:vetro|schermo|display)\b(?! posterior)", True),
        (r"\bvetro (?:rotto|crepato|incrinato)\b(?! dietro| posterior)", True),
        (r"\bnon funziona\w* (?:lo |il |la )?(?:schermo|display|touch)", True),
        (r"\b(?:manca lo schermo|senza schermo|linee verdi|riga verde)\b", False),
    ),
    "back-rotto": (
        (rf"\b(?:vetro posteriore|retro|scocca|back ?cover|parte posteriore|dietro){_BREAK}{{0,25}}"
         r"(?:rott|crepat|crepa\b|crepe|lesion|incrinat|da sostituire)", True),
        (rf"\b(?:rott|crepat|lesion)\w*{_BREAK}{{0,25}}\b(?:dietro|retro\b|vetro posteriore|"
         r"parte posteriore|scocca)", True),
    ),
    "batteria-esausta": (
        (rf"\bbatteria{_BREAK}{{0,30}}(?:da cambiare|da sostituire|da cambre|esausta|degradata|"
         r"\bko\b|scarsa|dura poco|gonfi|rigonfi|assistenza|da vedere|consigliabile sostituir)", True),
        (rf"\b(?:rigonfiamento|gonfia){_BREAK}{{0,12}}batteria", True),
        (r"\b(?:cambiare|cambre|sostituire) (?:la )?batteria\b", True),
        (r"\bda (?:vedere|cambiare|cambre|sostituire) (?:la )?batteria\b", True),
    ),
    "fotocamera-rotta": (
        (rf"\b(?:fotocamer\w*|camera\b|lente|lenti|vetrino){_BREAK}{{0,30}}"
         r"(?:non (?:\w+ )?funzion|rott|crepa|crepat|da riparare|difett|da sostituire)", True),
        (rf"\b(?:crepa|crepat|rott)\w*{_BREAK}{{0,30}}\bfotocamer", True),
        (r"\bno fotocamera\b", False),
    ),
    "face-id-rotto": (
        (rf"\bface ?id{_BREAK}{{0,20}}(?:non funzion|rott|problema|non disponibile|\bko\b|non va)", True),
        (r"\b(?:problema (?:con|al|del) (?:il )?face ?id|non funziona\w* (?:il |piu )?face ?id)", True),
        (r"\b(?:no|senza) face ?id\b", False),
    ),
    "audio-rotto": (
        (rf"\b(?:microfon\w*|altoparlant\w*|speaker|capsula|cassa|audio){_BREAK}{{0,30}}"
         r"(?:non (?:\w+ )?funzion|rott|basso|non si sente|difett|gracchi)", True),
        (r"\bsi sente (?:\w+ ){0,2}(?:basso|male)\b", True),
        (r"\bnon funziona\w* (?:il |la |i |le )?(?:microfon|altoparlant|cassa|capsula|speaker)", True),
    ),
    "ricarica-rotta": (
        (rf"\b(?:porta|connettore|attacco){_BREAK}{{0,20}}(?:ricarica|caricatore|lightning)"
         rf"{_BREAK}{{0,25}}(?:rott|allentat|non funzion|difett)", True),
        (rf"\b(?:caricatore|ricarica){_BREAK}{{0,12}}allentat", True),
        (r"\bnon (?:si )?carica\b", True),
    ),
    "tasti-rotti": (
        (rf"\b(?:tasto|tasti|tastino|home){_BREAK}{{0,25}}(?:rott|non funzion|danneggiat|saltat|difett)", True),
        (rf"\b(?:saltat|rott)\w*{_BREAK}{{0,10}}\btastin", True),
    ),
    "scheda-madre": (
        (r"\b(?:scheda madre|scheda logica|logic ?board)\b", False),
    ),
    "acqua": (
        (r"\b(?:caduto|caduta|finito|immerso)\w* (?:in|nell|nel|nella) ?(?:acqua|mare|piscina|lavatrice|wc)\b", True),
        (r"\b(?:ossidat\w*|ossidazione|danni da liquid\w*|contatto con (?:l )?acqua|bagnato)\b", True),
    ),
    "non-si-accende": (
        (r"\bnon si accende\b|\bnon da segni di vita\b|\bnon funziona piu\b", True),
        (rf"\b(?:iphone|telefono|cellulare|dispositivo|vende|vendo|venduto){_BREAK}{{0,25}}"
         r"(?<!sim )\bnon funzionante\b", True),
    ),
    "icloud-bloccato": (
        (r"\b(?:icloud bloccato|blocco (?:icloud|attivazione)|account icloud attivo|id apple bloccato|"
         r"imei bloccato|blacklist|bloccato con (?:password|codice)|non ricordo (?:la )?password|"
         r"codice dimenticato)\b", True),
    ),
    "altro-guasto": (
        (rf"\b(?:flash|nfc|apple pay|vibrazione|sensore){_BREAK}{{0,25}}(?:non funzion|non e attiv|rott|difett|sostituzione)", True),
        (r"\bnon funziona\w* (?:\w+ )?(?:il |la )?(?:flash|nfc|vibrazione)\b", True),
        (r"\bsostituzione (?:del )?sensore\b", True),
    ),
    # Venduto dichiaratamente per ricambi (non è un guasto ma un segnale forte).
    "per-ricambi": (
        (r"\b(?:per (?:i )?(?:pezzi )?(?:di )?ricambi\w*|come ricambi\w*|per pezzi|pezzi di ricambio|"
         r"solo ricambi|parti di ricambio)\b", True),
    ),
    # Segni estetici (difetto lieve): "graffi" storico + usura/ammaccature.
    "graffi": (
        (r"\b(?:graff\w*|segni (?:di|d) ?(?:usura|utilizzo)|segno\b|segni\b|ammacc\w*|sticchiatur\w*|"
         r"strisci\w*|botta|botte)\b", True),
    ),
}
_TECH_PATTERNS_RE = {
    code: tuple((re.compile(rx), neg) for rx, neg in patterns)
    for code, patterns in _TECH_PATTERNS.items()
}

# Accessorio subito prima del pezzo: il guasto è della pellicola, non del telefono.
_ACCESSORY_BEFORE_RE = re.compile(
    r"\b(?:pellicol\w*|vetro temperato|vetrino protett\w*|cover|custodia)\b[^.!?\n]{0,15}$"
)

# Parti NON originali dichiarate: pesano sul prezzo di rivendita.
_NON_ORIGINAL_PATTERNS = {
    "Schermo-Non-Originale": (
        re.compile(rf"\b(?:schermo|scermo|display|oled){_BREAK}{{0,35}}"
                   r"(?:non original\w*|compatibil\w*|non riconosciut\w*|aftermarket|non autentic\w*)"),
        re.compile(rf"\b(?:non original\w*|compatibil\w*){_BREAK}{{0,15}}\b(?:schermo|display)"),
    ),
    "Batteria-Non-Originale": (
        re.compile(rf"\bbatteri\w*{_BREAK}{{0,50}}(?:non original\w*|compatibil\w*|non autentic\w*)"),
        re.compile(r"\bparte sconosciuta\b"),
    ),
}


def _tech_defects_v2(norm: str, battery_pct: int | None) -> list[str]:
    found: list[str] = []
    for code, patterns in _TECH_PATTERNS_RE.items():
        for regex, respects_negation in patterns:
            if any(
                not (respects_negation and (
                    _negated(norm, m.start())
                    or _SPAN_REJECT_RE.search(m.group(0))
                    # "la pellicola sullo schermo è rotta": l'accessorio sta prima.
                    or _ACCESSORY_BEFORE_RE.search(norm[max(0, m.start() - 25):m.start()])
                ))
                for m in regex.finditer(norm)
            ):
                found.append(code)
                break
    # Salute batteria sotto il 70%: da sostituire anche se l'annuncio non lo dice.
    if battery_pct is not None and battery_pct < 70 and "batteria-esausta" not in found:
        found.append("batteria-esausta")
    return found


def _non_original_parts(norm: str) -> list[str]:
    return [
        feature
        for feature, patterns in _NON_ORIGINAL_PATTERNS.items()
        if any(p.search(norm) for p in patterns)
    ]


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
    # Apostrofi e punteggiatura interna come spazi: "com'è" / "c'è" → parole.
    norm = _normalize(raw).replace("'", " ").replace("’", " ")
    battery_pct = _extract_battery_pct(raw)

    # Difetti auto dal dizionario (negazione-aware); "graffi" esce dal
    # dizionario: lo copre il riconoscimento v2 con le negazioni.
    auto_synonyms = {k: v for k, v in _DEFECT_SYNONYMS.items() if k != "graffi"}
    defects = _match_dictionary(norm, auto_synonyms)
    for code in _tech_defects_v2(norm, battery_pct):
        if code not in defects:
            defects.append(code)
    features = _match_dictionary(norm, _FEATURE_SYNONYMS) + _match_dictionary(
        norm, _TECH_FEATURE_SYNONYMS
    )
    features += [f for f in _non_original_parts(norm) if f not in features]
    # "Batteria-Cambiata" nel corredo smentisce "batteria-esausta" letta altrove
    # (testi tipo "batteria da cambiare? No, appena sostituita" esistono), salvo
    # che la salute misurata sia comunque bassa.
    if ("Batteria-Cambiata" in features and "batteria-esausta" in defects
            and not (battery_pct is not None and battery_pct < 70)):
        defects.remove("batteria-esausta")

    return {
        "km": _extract_km(raw),
        "year": _extract_year(raw),
        "storage_gb": _extract_storage_gb(title, description),
        "battery_pct": battery_pct,
        "color": _extract_color(norm),
        "features": features,
        "defects_noted": defects,
        "urgency_flags": _match_dictionary(norm, _URGENCY_SYNONYMS),
        "exclude_from_iqr": any(d in _IQR_EXCLUSION_DEFECTS for d in defects),
        "is_accessory": _is_accessory_listing(title),
    }
