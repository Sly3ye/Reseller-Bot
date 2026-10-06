"""Tassonomia dei guasti iPhone (B3/B4 della release): UNA sola definizione
condivisa da regex, modello AI e serie di prova etichettata.

Per il business (comprare rotto → riparare → rivendere) non basta "rotto": serve
sapere COSA è rotto, perché da lì dipendono ricambio, costo e rischio:

- riparabili con ricambio a listino: schermo, scocca, batteria (services/parts.py)
- riparabili senza listino (ancora): fotocamera, face-id, audio, ricarica, tasti
- a rischio (lotteria): scheda-madre, acqua, non-si-accende
- invendibile: bloccato (iCloud / IMEI / codice)

Più due segnali che pesano sul prezzo di rivendita: **parti non originali**
(schermo/batteria già sostituiti con compatibili) e **segni estetici**; e se
l'annuncio è venduto dichiaratamente **per ricambi**.

Modulo puro (zero DB, zero rete) → testabile.
"""

from __future__ import annotations

from typing import Any

GUASTI = (
    "schermo", "scocca", "batteria", "fotocamera", "face-id", "audio", "ricarica",
    "tasti", "scheda-madre", "acqua", "non-si-accende", "bloccato", "altro",
)
PARTI = ("schermo", "batteria", "altro")

# Classi operative del guasto (per la UI e per la matrice opportunità).
GUASTO_CLASSE = {
    "schermo": "riparabile", "scocca": "riparabile", "batteria": "riparabile",
    "fotocamera": "riparabile", "face-id": "riparabile", "audio": "riparabile",
    "ricarica": "riparabile", "tasti": "riparabile", "altro": "riparabile",
    "scheda-madre": "rischio", "acqua": "rischio", "non-si-accende": "rischio",
    "bloccato": "invendibile",
}

# Codici storici dell'NLP (defects_noted) ↔ tassonomia. I codici storici restano
# quelli salvati in DB e letti da condition_tier / radar riparazioni.
NLP_TO_GUASTO = {
    "schermo-rotto": "schermo",
    "back-rotto": "scocca",
    "batteria-esausta": "batteria",
    "fotocamera-rotta": "fotocamera",
    "face-id-rotto": "face-id",
    "audio-rotto": "audio",
    "ricarica-rotta": "ricarica",
    "tasti-rotti": "tasti",
    "scheda-madre": "scheda-madre",
    "acqua": "acqua",
    "non-si-accende": "non-si-accende",
    "icloud-bloccato": "bloccato",
    "altro-guasto": "altro",
}
GUASTO_TO_NLP = {v: k for k, v in NLP_TO_GUASTO.items()}
NON_ORIGINAL_FEATURES = {
    "Schermo-Non-Originale": "schermo",
    "Batteria-Non-Originale": "batteria",
}


def from_nlp(defects: list[str] | None, features: list[str] | None) -> dict[str, Any]:
    """Etichetta nello schema della tassonomia a partire dall'output NLP."""
    defects = defects or []
    features = features or []
    return {
        "guasti": sorted({NLP_TO_GUASTO[d] for d in defects if d in NLP_TO_GUASTO}),
        "parti_non_originali": sorted(
            {NON_ORIGINAL_FEATURES[f] for f in features if f in NON_ORIGINAL_FEATURES}
        ),
        "segni_estetici": "graffi" in defects,
        "per_ricambi": "per-ricambi" in defects,
    }


# ------------------------------------------------------------------- AI v2

PROMPT_V2 = """Sei un tecnico che compra iPhone usati e rotti per ripararli e rivenderli.
Leggi l'annuncio e rispondi SOLO con un oggetto JSON valido con ESATTAMENTE questi campi:

- "guasti": lista dei guasti PRESENTI nel telefono, scegliendo SOLO tra:
  "schermo" (vetro/display rotto, crepato, righe, macchie, touch che non va),
  "scocca" (vetro posteriore o retro rotto/crepato),
  "batteria" (da sostituire, gonfia, "assistenza", sotto il 70%),
  "fotocamera" (fotocamera o suo vetrino rotto/non funzionante),
  "face-id", "audio" (microfono, altoparlante, capsula), "ricarica" (porta/connettore),
  "tasti", "scheda-madre" (guasta o mancante), "acqua" (caduto in acqua, ossidato),
  "non-si-accende" (morto, non funzionante nel complesso),
  "bloccato" (iCloud, IMEI in blacklist, codice dimenticato),
  "altro" (qualsiasi altro guasto: flash, NFC, sensori...).
  Lista vuota se il telefono è dichiarato funzionante e integro.
- "parti_non_originali": lista tra "schermo", "batteria", "altro" SOLO se l'annuncio dice
  che quella parte NON è originale (compatibile, non riconosciuta, "parte sconosciuta").
  "Batteria sostituita" senza dire che non è originale NON conta.
- "segni_estetici": true se dichiara graffi, segni d'usura o ammaccature sul telefono
  (non sulla pellicola o sulla cover), false altrimenti.
- "per_ricambi": true solo se è venduto dichiaratamente "per ricambi/pezzi".
- "motivo_prezzo": perché del prezzo in massimo 10 parole (o "").
- "rischio_truffa": "basso", "medio" o "alto".

ATTENZIONE alle negazioni: "nessun graffio", "senza crepe", "nessun blocco iCloud",
"Face ID funzionante" significano che quel problema NON c'è.
La percentuale di batteria da sola (es. 78%) non è un guasto se non sotto il 70%.

Titolo: {title}
Descrizione: {description}"""


# Guasti dell'AI che entrano nella condizione dell'annuncio (gli altri restano
# solo in ai_analysis, visibili nella scheda). Scelti sulla serie etichettata il
# 2026-10-06 con gemma4:e4b: F1 >= 0,89 e mai peggio delle regex. Esclusi per
# ora schermo/scocca/batteria (le regex sono già buone, l'AI li immagina su
# telefoni sani), "altro" (F1 0,35), ricarica (0,50), segni estetici (81%).
# Sovrascrivibile con AI_TRUSTED_GUASTI (lista separata da virgole).
AI_TRUSTED_DEFAULT = (
    "face-id", "fotocamera", "audio", "tasti", "scheda-madre", "acqua",
    "non-si-accende", "bloccato", "parti-non-originali", "per-ricambi",
)


def merge_ai_defects(
    defects: list[str] | None, features: list[str] | None, ai: dict[str, Any] | None,
    trusted: tuple[str, ...] | set[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Unisce ai codici NLP (regex) i guasti letti dall'AI (ai_analysis v3+).

    Le regex sono precise ma colgono meno della metà dei guasti (verifica del
    5/10): l'AI aggiunge, non toglie, e solo le voci in ``trusted`` (default
    AI_TRUSTED_GUASTI / AI_TRUSTED_DEFAULT; "parti-non-originali", "per-ricambi"
    e "segni-estetici" valgono per i rispettivi campi). La fonte dell'AI resta
    ``ai_analysis``, così ``reparse_nlp`` può rifare le regex e riapplicare
    questa unione senza perdere nulla. Senza analisi v3 ritorna l'input.
    """
    d = list(defects or [])
    f = list(features or [])
    if not ai or "guasti" not in ai:
        return d, f
    if trusted is None:
        from backend.core.config import settings  # noqa: PLC0415

        trusted = settings.ai_trusted_guasti or AI_TRUSTED_DEFAULT
    trusted = set(trusted)
    have = set(d)
    add = {GUASTO_TO_NLP[g] for g in ai.get("guasti") or [] if g in GUASTO_TO_NLP and g in trusted}
    if ai.get("per_ricambi") and "per-ricambi" in trusted:
        add.add("per-ricambi")
    if ai.get("segni_estetici") and "segni-estetici" in trusted:
        add.add("graffi")
    d += sorted(add - have)
    if "parti-non-originali" not in trusted:
        return d, f
    part_to_feature = {v: k for k, v in NON_ORIGINAL_FEATURES.items()}
    for part in ai.get("parti_non_originali") or []:
        feat = part_to_feature.get(part)
        if feat and feat not in f:
            f.append(feat)
    return d, f


def coerce_ai_v2(raw: dict[str, Any]) -> dict[str, Any]:
    """Valida l'output del modello nello schema della tassonomia."""

    def as_list(value: Any, allowed: tuple[str, ...]) -> list[str]:
        if isinstance(value, str):
            value = [value]
        if not isinstance(value, list):
            return []
        out = {str(v).strip().lower().replace(" ", "-") for v in value}
        return sorted(v for v in out if v in allowed)

    def as_bool(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() in ("true", "vero", "si", "sì", "1", "yes")
        return bool(value)

    risk = str(raw.get("rischio_truffa", "basso")).strip().lower()
    return {
        "guasti": as_list(raw.get("guasti"), GUASTI),
        "parti_non_originali": as_list(raw.get("parti_non_originali"), PARTI),
        "segni_estetici": as_bool(raw.get("segni_estetici")),
        "per_ricambi": as_bool(raw.get("per_ricambi")),
        "motivo_prezzo": str(raw.get("motivo_prezzo") or "")[:300],
        "rischio_truffa": risk if risk in ("basso", "medio", "alto") else "basso",
    }
