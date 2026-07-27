# Visione & Definizione di "fatto" — verticale iPhone

Documento vivo: fissa **schermate, analitiche e funzionalità** che vogliamo per
il verticale iPhone. Quando (quasi) tutto qui è ✅, l'iPhone è "chiuso" e si
passa alle **auto** (più modelli/denominazioni/parametri → più complesse).

Stato: ✅ fatto · 🔧 parziale (c'è ma da rifinire / matura coi dati) · ◻️ da fare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

> **Principio.** Per ogni annuncio e per ogni modello il sistema deve rispondere
> a 4 domande operative: **quanto vale davvero · quanto posso pagarlo · quanto e
> quando lo rivendo · di chi mi fido.** Coperte tutte, con dati affidabili e
> visibili in UI, l'iPhone è completo.

---

## 1. Feed / Live Sniper — *"cosa compro adesso"*

Lista filtrabile + card espandibile con assistente di trattativa.

- ✅ Filtri (modello, memoria, colore, condizione, classe affare, margine min,
  ricerca) + facets + paginazione + sort (score / recenti / margine)
- ✅ Card: badge condizione/classe affare/urgenza/riparazione/🟢 compra ora,
  specs (memoria, colore, batteria, luogo), Deal Score
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
- ◻️ 🟡 **Pagina/sezione Venditori** (ranking globale: più attivi / più
  motivati / finti privati) — oggi il profilo venditore è solo per-annuncio
- ◻️ 🟡 **Curva di deprezzamento per variante** (non solo top model) + confronto
  tra modelli
- 🔧 Sell-through, time-to-sale, prezzo di vendita reale: implementati, **maturano
  con i venduti** (il Garbage Collector deve accumulare `venduto_rimosso`)
- ⚪ **Stagionalità** (finestra keynote iPhone): bloccata finché non c'è storico
  `market_trends` di più mesi

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
- ◻️ 🟡 **Pannello salute scraper** (da `scrape_runs`): successi/errori, ultimo
  giro, alert down/ripristino, stato proxy / impersonation
- ◻️ 🟡 **Copertura**: n. target attivi, annunci/giorno, % gamma iPhone coperta

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
4. 🟡 **Pannello salute + copertura** (fiducia che il motore raccolga tutto)
5. 🟡 **Sezione Venditori** in Market Intelligence
6. ⚪ **Deprezzamento / stagionalità** — aspettano l'accumulo di storico

---

## Già solido (fondamenta, non toccare salvo rifiniture)

Scraper HTTP/JSON anti-Akamai (curl_cffi + proxy), NLP (memoria/colore/batteria/
difetti/corredo), varianti canoniche, valore equo **dai venduti**, Deal Score,
max bid, ROI/giorno, domanda-offerta, confidence, pHash anti-ripubblicazione,
shadow dealer, price history, Telegram intelligente, copertura gamma iPhone (31
target), Postgres self-hosted + Docker.

_Aggiungere qui le nuove idee man mano che emergono._
