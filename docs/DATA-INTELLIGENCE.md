# Data Intelligence: dal dato alla decisione d'acquisto

Lo scraping raccoglie i dati; questo layer li trasforma in **decisioni di
acquisto profittevoli**. Calcolato in lettura (`services/reads.py` +
`scoring.py` + `valuation.py` + `variants.py`), con euristiche trasparenti e
funzioni pure testate — nessun modello ML pesante da addestrare.

## Fase 1 — Varianti canoniche (scrematura)

Il principio: separare *come cerchi* (target/query) da *come analizzi*
(variante). Il resolver (`variants.py`) assegna a ogni annuncio una **variante
pulita**:
- **Tech**: `(modello, memoria)` → es. `iphone-13-pro-max-256`. Risolve
  l'overlap "iPhone 13" vs "13 Pro": non finiscono più nella stessa media.
- **Auto**: `(modello, generazione)` dal target → es. `bmw-123d-2007-2013`.
- **Condition tier**: `come-nuovo / buono / difetti / rotto|incidentata`.

Le medie di mercato sono calcolate **per variante**, solo dai listing **sani**
(esclude rotti/incidentati), ripulite con IQR.

## Fase 2 — Valutazione predittiva (`valuation.py`)

Dal "media della variante" al **valore equo del singolo annuncio**:
- **Valore equo** = mediana robusta della variante × fattore condizione; per le
  **auto**, il prezzo atteso a *quei* km (dal modello prezzo~km).
- **Posizione di mercato**: percentile del prezzo nella distribuzione
  ("più economico del X% dei simili").
- **Classificazione**: `affare` / `in-linea` / `caro` / **`sospetto`**. Il
  "sospetto" (troppo sotto il valore equo, spesso senza foto) **separa gli
  affari veri dalle esche/errori**, azzerando lo score così gli alert non ci
  cascano.

Il **Deal Score** usa il margine vs valore equo (più preciso della media).

## Deal Score (0–100) & assistente di trattativa (`scoring.py`)

- **Deal Score**: combina margine (fino a 55 pt, satura a +33%), freschezza,
  urgenza, tipo venditore (privato > finto_privato), calo prezzo, penalità
  difetti, batteria e corredo. Feed ordinabile, con breakdown leggibile.
- **Assistente di trattativa** (card espansa): offerta suggerita, giorni online,
  storico cali, storico venditore, e tasto → Pipeline P&L.
- **Radar riparazioni (tech)**: per gli iPhone rotti stima il costo (batteria
  ~79€, schermo 150–300€ per fascia, vetro post. ~120€) e ricalcola il **margine
  netto post-riparazione** — spesso un affare superiore al flip semplice.

## Time-to-sale & liquidità (C3)

Dai `venduto_rimosso` del Garbage Collector si misura in **quanti giorni ruota**
ogni modello (liquidità reale): un iPhone 13 con margine 18% che gira in 4gg
batte un 14 Pro con margine 25% invenduto da 3 settimane.

Il **valore equo** ora poggia sui **venduti** quando c'è campione sufficiente:
`_sold_variant_refs` calcola la mediana di realizzo per variante dai
`venduto_rimosso` sani (≥5 campioni) e la passa a `valuation` come riferimento
(precedenza: `prezzo~km` auto > **mediana venduti** > mediana listati). `fairValueSource`
dichiara la base usata. Finché i venduti non si accumulano, fallback ai listati.

> ℹ️ Il "prezzo di vendita rapida" (`fastSalePrice`) resta sui **listati** di
> proposito: per vendere in fretta ti posizioni sotto la **concorrenza attiva**.
> Il "quanto vale davvero" (`soldMedian`/`soldMax`) e il valore equo usano i venduti.

## Valutazione km-aware (auto)

Regressione lineare `prezzo ~ km` per target (≥8 campioni, pendenza negativa) →
prezzo atteso di quella specifica auto dati i suoi km.

## Analitiche operative (compravendita)

Costruite sui dati già raccolti, per passare dal "quanto vale" al "quanto pago
e cosa conviene davvero":

- **Max bid** (`scoring.max_bid`, per annuncio): il *tetto* d'acquisto per
  centrare il margine obiettivo = realizzo venduti − riparazione/penalità −
  margine. Diverso dall'offerta d'apertura (`suggestedOffer`): è il punto di
  walk-away. `buyAtAsking` = True quando conviene anche al prezzo richiesto.
- **ROI per giorno di capitale** (`roiPerDayPct`): margine ÷ giorni medi di
  vendita (dai venduti). È il nuovo ordinamento del "cosa comprare": un +18% che
  gira in 4gg batte un +25% fermo 3 settimane. A livello di modello e di annuncio.
- **Domanda/offerta** (`inflow7d`/`outflow7d`/`demandIndex`): venduti vs nuovi
  immessi nell'ultima settimana per variante. `demandIndex > 1` = si vende più in
  fretta di quanto entra offerta → pressione prezzi al rialzo ("comprare ora").
- **Confidence della valutazione** (`valuationConfidence` + `valuationSamples`):
  quanti campioni (attivi + venduti) sostengono il valore equo → ti fidi degli
  affari "solidi" ed eviti di agire su pool sottili.

## Pipeline P&L (`api/deals.py`)

Il gestionale: ogni affare attraversa `interessante → contattato → offerta →
comprato → in_vendita → venduto`, con prezzo pagato, costi accessori e prezzo di
rivendita → **profitto netto reale**. Chiude il feedback loop: confronta il
margine stimato dal bot con quello effettivamente incassato.
