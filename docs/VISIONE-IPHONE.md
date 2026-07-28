# Visione & Definizione di "fatto" — verticale iPhone

Documento vivo: fissa **schermate, analitiche e funzionalità** che vogliamo per
il verticale iPhone. Quando (quasi) tutto qui è ✅, l'iPhone è "chiuso" e si
passa alle **auto** (più modelli/denominazioni/parametri → più complesse).

Stato: ✅ fatto · 🔧 parziale (c'è ma da rifinire / matura coi dati) · ◻️ da fare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

> **Principio.** Per ogni annuncio e per ogni modello il sistema deve rispondere
> a 5 domande operative: **quanto vale davvero · quanto posso pagarlo · quanto e
> quando lo rivendo · di chi mi fido · è sicuro comprarlo.** Coperte tutte, con
> dati affidabili e visibili in UI, l'iPhone è completo.

---

## 1. Feed / Live Sniper — *"cosa compro adesso"*

Lista filtrabile + card espandibile con assistente di trattativa.

- ✅ Filtri (modello, memoria, colore, condizione, classe affare, margine min,
  ricerca) + facets + paginazione + sort (score / recenti / margine)
- ✅ Card: badge condizione/classe affare/urgenza/riparazione/🟢 compra ora/
  🛑 rischio/↓ motivato, specs (memoria, colore, batteria, luogo), Deal Score
- ✅ **Risk Score anti-frode** (5ª domanda "è sicuro comprarlo"): semaforo che
  aggrega iCloud lock, pattern truffa a distanza (pagamento anticipato / no
  ritiro), prezzo sospetto, finto-privato, venditore senza storico; badge in
  card + pannello motivi nell'espansa. Dati già estratti, zero re-scrape.
- ✅ **Watch di prezzo** (E): storico completo dei ribassi del singolo annuncio
  (quante volte, quanto in € e %, da quanti giorni fermo) → quanto è motivato
  il venditore. Badge "↓ motivato" in card + chip "Ribassi" nell'espansa.
- ✅ Espansa: valore equo (fonte + affidabilità), **max bid**, offerta
  consigliata, **ROI/giorno**, ribasso, **venditore + profilo motivato**,
  margine netto post-riparazione (solo ricambio Apple), analisi AI, breakdown
  score, galleria + lightbox
- ✅ **Azioni sull'annuncio**: salva ⭐ / scarta 🗑 (nascondi) per riga,
  persistite (`triage`); viste Attivi / Salvati / Tutti.
- ✅ **Preset rapidi**: 🟢 compra ora, 🎯 motivati, 🔧 riparabili
- ✅ **Sort per ROI/giorno** (oltre a score/recenti/margine)

## 2. Market Intelligence — *"cosa conviene / come si muove il mercato"* (anche HOME)

È la landing del verticale: niente schermata KPI separata e ridondante.

- ✅ KPI (annunci attivi, prezzo medio, giorni medi di vendita, migliore
  opportunità) + trend chart
- ✅ "Cosa comprare" ordinato per **ROI/giorno** + dettaglio per modello: box
  prezzi, **domanda/offerta 7gg**, **momentum prezzo**, premio memoria, impatto
  condizione, prezzo→giorni, distribuzione motivi AI, venditori / finti privati
- ✅ **Sezione Venditori** (ranking globale: più attivi / più motivati / finti
  privati) — la priorità di contatto
- ✅ **Liquidità per variante** (F): indice 0-100 + livello 💧 alta/media/bassa
  (sell-through, giorni di vendita, domanda/offerta) accanto a ogni modello +
  offerta per taglio di memoria (annunci attivi). Distingue margine alto ma
  illiquido (capitale fermo) dall'affare che gira davvero.
- ✅ **Curva di deprezzamento per variante** + confronto tra modelli: prezzo
  mediano per **età del modello**, una curva per linea (base/Plus/Pro/Pro Max) e
  taglio di memoria. Dà **perdita attesa a 12 mesi** (€ e %), **costo di
  magazzino** (€/mese di capitale che evapora) e **valore residuo %** fra
  generazioni. Cross-sezionale (il 14 Pro di oggi = il 15 Pro fra un anno),
  quindi leggibile subito senza aspettare mesi di `market_trends`.
- 🔧 Sell-through, time-to-sale, prezzo di vendita reale: implementati, **maturano
  con i venduti** (il Garbage Collector deve accumulare `venduto_rimosso`)
- ⚪ **Stagionalità** (finestra keynote iPhone): bloccata finché non c'è storico
  `market_trends` di più mesi

## 2b. Tempo di vendita — *"quanti giorni ci mette a vendersi"* (schermata dedicata)

- ✅ **Pivot dei giorni di vendita** dai venduti (`venduto_rimosso`,
  found→sparizione): si sceglie di raggruppare per **modello / colore / taglia**
  in qualsiasi combinazione (uno, due, tutti o totale) e si filtra per valore
  (es. un modello → giorni per ogni suo colore). Tabella ordinata dal più veloce,
  con campione e prezzo mediano; righe sotto 3 venduti marcate come fragili.
  Dati già presenti, nuova dimensione colore/taglia prima inutilizzata.

## 3. Pipeline P&L — *"il gestionale che chiude il loop"*

- ✅ Stadi interessante → contattato → offerta → comprato → in_vendita →
  venduto / sfumato; costi accessori; profitto netto; riepilogo (investito,
  realizzato, margine reale medio)
- ✅ **Feedback loop visibile**: accuratezza stime, scarto medio (sotto/sovra-
  stima), stima→reale medio per i venduti
- ✅ **ROI/giorno realizzato** (margine reale ÷ giorni in stock)
- ◻️ ⚪ Tempo-in-stadio + alert "in vendita da troppo"

## 4. Automations / Salute — *"il motore gira bene?"*

- ✅ Job: avvio immediato, pausa/ripresa, cambio intervallo, prossima esecuzione
- ✅ **Pannello salute scraper** (da `scrape_runs`): stato per categoria,
  timeline ultimi giri, ultimo giro, stato proxy / impersonation
- ✅ **Copertura**: target attivi, annunci in magazzino, nuovi/24h per categoria

## 5. Impostazioni — *"configura senza toccare il codice"*

- ✅ **Impostazioni da UI**: soglie alert (score/margine/calo), margine obiettivo
  per categoria, **prezzi ricambi Apple** per fascia, chat Telegram. Salvate in
  `app_settings`, applicate a runtime (il token bot resta in `.env`).

> Scartati di proposito: **Home/Overview separata** (la fa Market Intelligence) e
> **storico notifiche** (già sul telefono via Telegram).

---

## Gap prioritari per "chiudere iPhone"

1. ✅ **Azioni sul feed** (salva/scarta + preset + sort ROI) — FATTO
2. ✅ **Impostazioni da UI** (soglie, margine, prezzi ricambi Apple, Telegram) — FATTO
3. ✅ **Feedback loop P&L** (previsto vs reale) — FATTO
4. ✅ **Pannello salute + copertura** — FATTO
5. ✅ **Sezione Venditori** in Market Intelligence — FATTO
6. ✅ **Curva di deprezzamento** per variante + confronto modelli — FATTO
7. ⚪ **Stagionalità** (finestra keynote) — aspetta l'accumulo di storico

> **Stato: tutti i gap implementabili sono chiusi.** Resta solo la ⚪
> stagionalità, che dipende dall'accumulo di mesi di `market_trends` e non si
> può anticipare. Il verticale iPhone è completo e utilizzabile: si passa alle
> **auto**.

---

## Già solido (fondamenta, non toccare salvo rifiniture)

Scraper HTTP/JSON anti-Akamai (curl_cffi + proxy), NLP (memoria/colore/batteria/
difetti/corredo), varianti canoniche, valore equo **dai venduti**, Deal Score,
max bid, ROI/giorno, domanda-offerta, confidence, pHash anti-ripubblicazione,
shadow dealer, price history, Telegram intelligente, copertura gamma iPhone
(gamma completa fino alla gen 17, linea Air inclusa), Postgres self-hosted +
Docker.

> ⚠️ **La gamma va tenuta al passo.** La flotta era ferma alla gen 16 mentre il
> 17 (17/Air/Pro/Pro Max/17e) era già sul mercato da mesi: modelli più cari,
> quindi più margine per pezzo, completamente ciechi. A ogni keynote: aggiungere
> la generazione in `scripts/seed_iphone_targets.py` **e** verificare che il
> resolver di variante conosca eventuali linee nuove (l'Air non c'era, e un
> "17 Air" finiva nel pool del 17 base a ~100€ di differenza).

_Aggiungere qui le nuove idee man mano che emergono._
