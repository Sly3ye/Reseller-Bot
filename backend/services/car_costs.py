"""Costi d'acquisto di un'auto usata: il margine "vero" di un flip.

Prezzo di rivendita − prezzo pagato non è il guadagno: chi compra paga il
passaggio di proprietà (soprattutto l'IPT, che dipende dai kW e dalla
provincia), spesso un'agenzia, e prepara l'auto prima di rivenderla.

Importi del passaggio (verificati il 2026-10-05):
- IPT (Imposta Provinciale di Trascrizione), D.M. 27/11/1998 n. 435: 150,81 €
  fino a 53 kW; oltre, 3,5119 € per ogni kW. Le province possono aumentarla
  fino al 30% (art. 56 D.Lgs. 446/1997): la maggior parte applica il massimo,
  ma va controllata la delibera della provincia di chi intesta l'auto.
- Emolumenti ACI 27,00 € (13,50 € per l'annotazione a favore di chi fa
  commercio di veicoli usati); diritti Motorizzazione 10,20 €; imposta di
  bollo 32 € (istanza) + 16 € (Documento Unico) + 16 € (autentica).
Fonti: aci.it "Costi del passaggio di proprietà", aci.gov.it "Passaggio di
proprietà: trascrizione". Agenzia e preparazione sono del singolo: si
impostano nelle Impostazioni (default 0 = non conteggiate).
"""

from __future__ import annotations

import re
from typing import Any

IPT_BASE_EUR = 150.81        # fino a 53 kW
IPT_KW_THRESHOLD = 53
IPT_PER_KW_EUR = 3.5119      # oltre 53 kW, per ogni kW
EMOLUMENTI_ACI_EUR = 27.00
EMOLUMENTI_ACI_DEALER_EUR = 13.50
DIRITTI_MOTORIZZAZIONE_EUR = 10.20
BOLLI_EUR = 32.0 + 16.0 + 16.0

# Impostazioni (sovrascritte da settings_store → configure()).
CONFIG: dict[str, Any] = {
    "car_ipt_province_pct": 30.0,   # maggiorazione provinciale (0–30)
    "car_agency_eur": 0.0,          # agenzia pratiche auto, se la usi
    "car_prep_eur": 0.0,            # preparazione: lavaggio, piccoli ritocchi, tagliando
    "car_dealer": False,            # commerciante: emolumento ACI ridotto
}


def configure(cfg: dict[str, Any]) -> None:
    for key in CONFIG:
        if key in cfg and cfg[key] is not None:
            CONFIG[key] = cfg[key]


def ipt_eur(kw: int | None, province_pct: float | None = None) -> float | None:
    """IPT del passaggio per un autoveicolo di ``kw`` kW, o None se ignoti."""
    if not kw or kw <= 0:
        return None
    pct = CONFIG["car_ipt_province_pct"] if province_pct is None else province_pct
    pct = min(max(float(pct), 0.0), 30.0)
    base = IPT_BASE_EUR if kw <= IPT_KW_THRESHOLD else IPT_PER_KW_EUR * kw
    return round(base * (1 + pct / 100), 2)


_CV_RE = re.compile(r"\b(\d{2,3})\s*(?:cv|hp)\b", re.IGNORECASE)
_KW_RE = re.compile(r"\b(\d{2,3})\s*kw\b", re.IGNORECASE)


def kw_from_text(text: str | None) -> int | None:
    """Potenza scritta nell'annuncio ("218cv", "150 kW") quando manca il campo."""
    if not text:
        return None
    if m := _KW_RE.search(text):
        return int(m.group(1))
    if m := _CV_RE.search(text):
        return round(int(m.group(1)) * 0.7355)  # 1 CV = 0,7355 kW
    return None


def acquisition_costs(kw: int | None, estimated: bool = False) -> dict[str, Any]:
    """Costi d'acquisto con il dettaglio. ``total`` None se i kW sono ignoti
    (l'IPT ne dipende: meglio nessuna cifra che una inventata).
    ``estimated``: kW non dal campo di Subito ma dal testo o dalla variante."""
    ipt = ipt_eur(kw)
    emolumenti = EMOLUMENTI_ACI_DEALER_EUR if CONFIG["car_dealer"] else EMOLUMENTI_ACI_EUR
    fixed = emolumenti + DIRITTI_MOTORIZZAZIONE_EUR + BOLLI_EUR
    agency = float(CONFIG["car_agency_eur"] or 0)
    prep = float(CONFIG["car_prep_eur"] or 0)
    return {
        "kw": kw,
        "kwEstimated": estimated,
        "ipt": ipt,
        "iptProvincePct": float(CONFIG["car_ipt_province_pct"]),
        "fees": round(fixed, 2),
        "agency": agency,
        "prep": prep,
        "transfer": round(ipt + fixed, 2) if ipt is not None else None,
        "total": round(ipt + fixed + agency + prep, 2) if ipt is not None else None,
    }
