# Roadmap & Backlog

Stato: ✅ fatto · 🔜 pianificato · 💡 idea da valutare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

> **Focus attuale: verticale iPhone/tech.** Il verticale auto ha molti più
> modelli, denominazioni e parametri — a livello di gestione dati è più
> complesso e viene affrontato dopo aver consolidato il tech.

---

## Fasi BI (piano strutturale)

| Fase | Contenuto | Stato |
|---|---|---|
| **Fase 1** | Tassonomia canonica & scrematura (varianti, condizione) | ✅ |
| **Fase 2** | Valutazione predittiva (valore equo, posizione, affare-vs-truffa) | ✅ |
| **Fase 3 — robustezza** | Salute scraper, alert down, rotazione impersonation | ✅ |
| **Fase 3 — scala** | Generazione sistematica dei target (gamma auto) | 🔜 |
| **Fase 4** | Profili venditore, stagionalità, CV foto, multi-piattaforma | 🔜 |
| **Fase 5** | Ops: deploy VPS, automations reali, test, migration runner | 🔜 (dopo aver sistemato il resto) |

---

## Richieste da implementare (backlog)

### 1. 🔴 Time-to-sale per fascia di prezzo + prezzo di vendita REALE
**Problema osservato:** vedere molti annunci a un certo prezzo **non** significa
che si venda a quel prezzo. Il "prezzo di rivendita suggerito" attuale usa la
distribuzione dei prezzi **listati (attivi)**, che è un segnale distorto.

**Da implementare:**
- Per ogni modello/variante, incrociare `found_at` → data di rimozione (dal
  Garbage Collector) con l'`asking_price` all'atto della sparizione → curva
  **"a quale prezzo si vende in quanti giorni"**.
- **Prezzo di vendita realistico** = distribuzione dei prezzi degli annunci
  **spariti** (venduti), non di quelli listati (p25/p50 dei venduti).
- **Prezzo di vendita più alto** effettivamente raggiunto (venduto), non il più
  alto messo in vetrina.
- Tempi di vendita per fascia di prezzo (es. "a 400€ si vende in ~5gg, a 480€ in
  ~30gg").

**Note tecniche:** oggi il GC marca `venduto_rimosso` con la data in
`updated_at`; serve conservare anche l'ultimo `asking_price` visto prima della
rimozione. Sostituire/affiancare `_resale_suggestions` (basato sui listati) con
un calcolo sui venduti.

### 2. ⚪ Popup immagine richiudibile (X / ESC)
Nel frontend, cliccando un'immagine non deve aprirsi una nuova finestra/scheda,
ma un **modal (lightbox)** sopra la dashboard, chiudibile con la **X** o con
**ESC** (e click sullo sfondo). Riguarda la galleria nella card espansa del feed.

### 3. 🔴 AI locale per l'analisi delle descrizioni
**Obiettivo:** far leggere titolo+descrizione a un **LLM locale** (es. Ollama con
un modello piccolo) per capire *semanticamente* ciò che le regex non colgono:
- Il **motivo** di un prezzo basso → così un annuncio a buon prezzo con una
  spiegazione legittima non viene bollato come "sospetto" (riduce i falsi
  positivi del deal-vs-scam della Fase 2).
- La **riparabilità**: se il telefono è ancora più un affare perché si può
  cambiare schermo/batteria/scocca e rivendere con margine (potenzia il radar
  riparazioni).
- Difetti/segnali non catturati dai dizionari regex; segnali di autenticità/scam.

**Note:** già pianificato concettualmente (era la "CV/AI" della Fase 4);
promosso perché ad alto valore. Locale = nessun costo per-token, dati in casa.
Va integrato con `scoring.py` (radar riparazioni) e `valuation.py` (scam).

### 4. 🟡 Documentazione (questo documento + `docs/`)
README splittato in documenti tematici collegati; README ridotto a spiegazione
del programma, architettura e comandi. ✅ (in corso/fatto)

### 5. 🔴 Dashboard principale: mostrare TUTTO l'accumulato, i migliori, con filtri
Oggi la dashboard ("Live Sniper") mostra solo gli **ultimi ~60** annunci
(ordine per data). Deve invece:
- Mostrare **tutti** gli annunci accumulati (attivi), **ordinati per i migliori**
  (Deal Score), con **paginazione**.
- **Filtri (iPhone):** modello, taglia (storage), **colore**, condizione,
  fascia di prezzo, classe affare, ecc.
- Valutare rinomina: "Live Sniper" implica "ultimi"; ora è "tutte le migliori
  opportunità".

**Note tecniche:** serve estrazione del **colore** (nuovo campo NLP), un
endpoint `/api/opportunities` con **filtri + paginazione + ordinamento server**,
e la UI dei filtri. Attenzione al costo del calcolo BI su molti annunci
(materializzare le medie/pool per variante).

### 6. 🟡 Market Intelligence: più analitiche (proposte)
Da aggiungere alla schermata (per iPhone):
- **Distribuzione prezzi per variante** (box plot / istogramma) — la dispersione,
  non solo la media.
- **Curva di deprezzamento** per modello nel tempo (dati già in `market_trends`).
- **Time-to-sale per fascia di prezzo** (dal punto 1).
- **Prezzo di vendita realistico** (venduti, non listati).
- **Liquidità/volume** per variante (n. annunci attivi).
- **Sell-through rate**: % di annunci che spariscono (venduti) vs restano, per modello.
- **Ranking margine × liquidità**: i modelli che rendono di più *e* girano in fretta.
- **Stagionalità**: prezzo medio per settimana/mese (effetto keynote iPhone).
- **Spread affare**: differenza p10 ↔ mediana per variante = quanto margine c'è
  da cacciare.
- **Premio memoria**: differenziale di prezzo 128 → 256 → 512 per modello.
- **Distribuzione condizioni** (come-nuovo/buono/difetti) e impatto sul prezzo.
- **Venditori più attivi / finti privati** per modello.

---

## Refinement già annotati

- 🟡 **NLP storage**: i GB sono estratti solo dal ~30% dei titoli (spesso in
  descrizione o assenti) → migliorare l'estrazione (anche via AI locale, punto 3)
  per la finezza per-memoria dei margini.
- 🔴 **Colore iPhone**: nuovo campo NLP, necessario per i filtri (punto 5).
- 🟡 **Prezzo di rivendita dai venduti** (vedi punto 1): l'attuale usa i listati.
- ⚪ **Automations panel reale**: i controlli (Force Run, intervallo) sono ancora
  dimostrativi; collegarli a endpoint di controllo job (Fase 5).
- ⚪ **Migration runner** versionato per aggiornamenti incrementali dello schema.
- 🟡 **Verticale auto**: catalogo modelli×generazioni completo, denominazioni,
  parametri — rimandato (più complesso del tech).

---

## Idee future (💡)

- Multi-piattaforma (AutoScout24, Vinted, Facebook Marketplace) per arbitraggio
  cross-platform (compro su A, rivendo su B).
- Computer Vision sulle foto: rilevare condizione/danni, foto-stock (scam),
  verifica che l'oggetto corrisponda al titolo.
- Frontend real-time (SSE/WebSocket) invece del polling.
