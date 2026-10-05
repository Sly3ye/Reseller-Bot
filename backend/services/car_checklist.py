"""Cosa controllare prima di comprare un'auto usata (VISIONE-AUTO §2).

Regole meccaniche GENERALI scelte dai dati dell'annuncio (carburante, km,
età, cambio, carrozzeria, difetti dichiarati): niente difetti specifici di un
modello scritti a memoria — quelli arriveranno con fonti verificabili o con
l'AI. Ogni voce dice cosa guardare e perché conta per il prezzo.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def checklist(row: dict[str, Any], features: list[str] | None = None,
              defects: list[str] | None = None) -> list[dict[str, str]]:
    features = features or []
    defects = defects or []
    year = row.get("year")
    km = row.get("km")
    age = datetime.now(timezone.utc).year - int(year) if year else None
    fuel = (row.get("fuel") or "").lower()
    gearbox = (row.get("transmission") or "").lower()
    body = (row.get("body_type") or "").lower()
    title = f"{row.get('title') or ''} {row.get('description') or ''}".lower()
    items: list[dict[str, str]] = []

    def add(what: str, why: str) -> None:
        items.append({"what": what, "why": why})

    add("Visura PRA", "proprietari, fermi amministrativi, ipoteche: con un fermo il passaggio non si fa")
    add("Km all'ultima revisione",
        "sul Portale dell'Automobilista con la targa: se sono più alti di quelli dichiarati, km scalati")
    add("Spessimetro sulla carrozzeria", "vernice rifatta = urto non dichiarato, pesa sul prezzo di rivendita")
    add("Prova a freddo e diagnosi OBD", "fumo, rumori all'avvio, spie e codici errore memorizzati nelle centraline")
    add("Gomme e freni", "usura e anno delle gomme (DOT): un treno nuovo sono centinaia di euro")
    if "Distribuzione-Fatta" in features:
        add("Fattura della distribuzione", "dichiarata fatta: senza fattura va considerata da fare")
    elif (km or 0) >= 100000 or (age or 0) >= 8:
        add("Distribuzione (cinghia o catena)", "quando è stata fatta: rifarla costa da qualche centinaio a oltre mille euro")
    if "diesel" in fuel:
        add("FAP/DPF ed EGR", "rigenerazioni, fumo, perdita di potenza: problemi tipici dei diesel moderni")
        if (km or 0) >= 120000:
            add("Iniettori e volano bimassa", "vibrazioni alla partenza e al minimo, avviamento difficile")
    if (km or 0) >= 150000 or (age or 0) >= 10:
        add("Frizione e sospensioni", "slittamento in salita, silent block e ammortizzatori consumati")
        add("Ruggine sotto la scocca", "longheroni, passaruota, attacchi sospensioni: oltre i 10 anni conta molto")
    if gearbox.startswith(("autom", "sequen")):
        add("Cambio automatico", "scalate a freddo e a caldo, strappi, olio cambio sostituito secondo manutenzione")
    if "gpl" in fuel or "metano" in fuel or "gpl" in title or "metano" in title:
        add("Bombole GPL/metano", "scadenza o revisione delle bombole riportata sul libretto: sostituirle costa")
    if "cabrio" in body or "cabrio" in title:
        add("Capote", "tenuta all'acqua, meccanismo e lunotto: le riparazioni sono care")
    if "ibrid" in fuel or "elettric" in fuel or "hybrid" in title:
        add("Batteria di trazione", "stato di salute (SOH) e garanzia residua della batteria")
    if "incidentata" in defects:
        add("Telaio e airbag", "incidentata dichiarata: misure del telaio e airbag non esplosi, non solo la carrozzeria")
    if row.get("seller_type") == "finto_privato":
        add("Chi vende davvero", "probabile rivenditore che si presenta come privato: niente garanzia legale")
    return items
