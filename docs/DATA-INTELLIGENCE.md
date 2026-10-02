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

**Modelli canonici (tech).** Il resolver riconosce ogni iPhone reale, dal 4 al
18: numerici (anche a una cifra: 8, 6s, 5c), a lettere (X, XR, XS, XS Max, SE),
la linea Air ("iPhone Air", con o senza "17"), i refusi ("I phone", "Iphon").
Ogni combinazione viene validata contro la gamma Apple vera (`_is_real_iphone`:
mini solo 12-13, Plus solo 14-16, "e" dalla 16, tetto `MAX_IPHONE_GEN`): un
"iPhone 17 mini" o un "iPhone 12 e cover" non diventano modelli inventati.

**Statistiche per modello, non per target.** Market Intelligence, venduti e
tempo di vendita raggruppano per il **modello del titolo** (`_row_model`, dalla
variante canonica), non per il target della query che ha trovato l'annuncio.
Così entrano anche gli iPhone senza target e nessun "13 Pro" finisce sotto il
"13". Le auto restano per target (la variante auto è il target).

**Letture complete.** Le statistiche leggono tutto lo stock (`_select_all`,
paginato), non più un campione con `limit(2000/5000/20000)`. Il feed delle
opportunità è in cache 90s (`_enriched_feed`); il triage si rilegge fresco.

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

Dai `venduto_rimosso` (inventario tech / Garbage Collector auto) si misura in
**quanti giorni ruota** ogni modello (liquidità reale): un iPhone 13 con
margine 18% che gira in 4gg batte un 14 Pro con margine 25% invenduto da 3
settimane. I giorni partono da `published_at` (pubblicazione su Subito) quando
c'è, altrimenti da `found_at`.

**Kaplan–Meier (`survival.py`).** La media dei soli spariti è ottimista: chi
resta online mesi non conta, i venduti in 2 giorni sì. La stima di
sopravvivenza usa anche gli annunci ancora attivi come "censurati" (a N giorni
non ancora venduti): `daysToSellKM` = giorni entro cui si vende metà degli
annunci, più `sold7dPct` / `sold30dPct`. `null` = meno di metà venduta nella
finestra osservata (dato onesto, non un buco). ROI per giorno e costo di
magazzino usano il dato KM quando c'è; `avgDaysToSell` resta per confronto.

**Venduto, scaduto o ritirato (`removal_kind`).** Subito non dice perché un
annuncio sparisce. Euristica dichiarata: oltre ~11 mesi → **scaduto**; online
≥90gg, mai ribassato e ≥10% sopra la mediana di mercato → **ritirato**;
altrimenti **venduto**. Scaduti e ritirati restano censurati in KM e fuori da
prezzi di realizzo e grafico prezzo×giorni (`removalKinds` ne dà il conteggio).

**Ripubblicazioni (`republish.py`).** Cancellare e ripubblicare lo stesso
telefono produceva una vendita falsa + un annuncio "nuovo". Oltre al pHash
della foto, si riconosce senza foto: stesso venditore + stessa variante
(modello riconosciuto) + prezzo ±15%, con una regola temporale che salva i
negozi con più pezzi uguali. Allo Sniper il record sparito torna attivo con il
nuovo URL; all'inventario il gemello si fonde nel record originale (storico
prezzi e pipeline compresi). In entrambi i casi resta la data di nascita vera.

**Storico prezzi completo.** `price_history` registra anche i rialzi (prima
solo i cali); le letture sui ribassi filtrano i cali, il Watch di prezzo
conta anche i rialzi (`riseCount`: venditore senza fretta).

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
- **Costo di magazzino** (`carryCost`, per annuncio): deprezzamento della
  variante × giorni attesi di vendita, **sottratto dal max bid**. È un costo
  reale dell'operazione come il ricambio. Finché i venduti non bastano a
  misurare i giorni, si assume un mese (`DEFAULT_HOLD_DAYS`) e il payload lo
  dichiara (`estimatedDays`), così in UI si distingue la stima dal dato.
- **Confidence della valutazione** (`valuationConfidence` + `valuationSamples`):
  quanti campioni (attivi + venduti) sostengono il valore equo → ti fidi degli
  affari "solidi" ed eviti di agire su pool sottili.

## Curva di deprezzamento (`depreciation.py`)

Quanto vale un iPhone **in funzione di quanti anni ha**, e quanto costa tenerlo
fermo. Approccio **cross-sezionale**: a parità di linea (base/mini/Plus/Pro/Pro
Max/"e") e di memoria, i modelli in vendita oggi sono lo stesso oggetto a età
diverse — la mediana del 14 Pro 256GB di oggi stima quanto varrà il 15 Pro
256GB fra un anno. Nessuna raccolta aggiuntiva: parte dai pool per variante già
IQR-puliti della valutazione (≥3 annunci per variante, ≥2 generazioni per linea).

- **Perdita a 12 mesi** (€ e %): salto verso la generazione precedente,
  annualizzato sulla distanza d'età reale fra le due.
- **Costo di magazzino** (€/mese): quella perdita ÷ 12 — il capitale che evapora
  mentre l'annuncio è fermo. Da leggere insieme alla **liquidità**: margine alto
  + bassa liquidità + deprezzamento veloce = affare che si mangia da solo.
- **Valore residuo %**: rispetto al modello più recente della stessa linea → il
  confronto diretto fra generazioni.

Le date di uscita sono una **regola, non una tabella**: settembre dell'anno
`2008 + numero` (13→2021 … 17→2025), febbraio dell'anno dopo per la linea "e"
(16e → feb 2025). Vale anche per i modelli non ancora usciti, quindi non va
aggiornata a ogni keynote.

> ⚠️ Diverso dal **trend storico** di `market_trends` (come si è mosso il prezzo
> di *questo* modello nei giorni scorsi), che richiede mesi di storico. Questa
> curva è leggibile dal primo giorno di raccolta.

## Pipeline P&L (`api/deals.py`)

Il gestionale: ogni affare attraversa `interessante → contattato → offerta →
comprato → in_vendita → venduto`, con prezzo pagato, costi accessori e prezzo di
rivendita → **profitto netto reale**. Chiude il feedback loop: confronta il
margine stimato dal bot con quello effettivamente incassato.

**Affari fermi** (`daysInStage` / `stale`): ``updated_at`` cambia a ogni
passaggio di stadio, quindi misura da quanto un affare è fermo *lì*. Oltre la
soglia dello stadio scatta l'allerta (critico al doppio), e sui pezzi già
comprati viene quantificato il **deprezzamento maturato**: "fermo da 65 giorni"
diventa "ti è già costato 63€", che è l'unica formulazione che fa agire.
