# Goal Version — dove deve arrivare FlipRadar per battere il mercato

> Analisi del 2026-10-05 su tutto il codice (≈12.800 righe backend, 7.800
> frontend, 24 migrazioni, 40 script) e su tutti i documenti di progetto.
> Ogni affermazione marcata **[misurato]** è stata verificata sul sistema
> vivo quel giorno; il resto è ragionamento, dichiarato come tale.
> Sostituisce come **nord** [RELEASE.md](RELEASE.md) (che resta la lista di
> controllo dei criteri) e le VISIONE-* (che restano l'inventario funzioni).

## Il nord, in una riga

Nell'usato vince chi **vede l'occasione per primo, sa il margine vero prima
degli altri, manda per primo un'offerta credibile e impara dai propri
affari**. Tutto ciò che non accorcia uno di questi quattro tempi o non rende
più vero il margine è rumore.

## 0. Diagnosi: sei fatti che cambiano le priorità

| # | Fatto | Evidenza |
|---|---|---|
| F1 | **Gli alert con foto non arriverebbero.** `sendPhoto` riceve l'URL locale della foto (`http://localhost:8000/media/...`, default di `PUBLIC_MEDIA_BASE_URL`): Telegram non può scaricarlo, rifiuta il messaggio, e non c'è ripiego sul solo testo. | `notifications._send_telegram`, `docker-compose.yml` **[misurato sul codice]** |
| F2 | **La nostra latenza è il doppio del necessario.** L'indice di ricerca di Subito è ~6 minuti dietro la pubblicazione (pavimento per chiunque): l'annuncio più recente in pagina 1 aveva 6 minuti. Sopra, aggiungiamo in media 7,5 min (giro ogni 15) per gli iPhone e 15 (giro ogni 30) per le auto, più il download delle foto *prima* dell'inserimento e dell'alert. | sonde su hades, `scrape_runs`, `tasks.persist_opportunities` **[misurato]** |
| F3 | **La data "di pubblicazione" di Subito si resetta coi riposizionamenti.** Un annuncio trovato il 2/10 alle 11:15 oggi risulta pubblicato alle 10:55. Le prime pagine sono piene di annunci vecchi rimessi in cima: lo sweep auto rilegge 20–30 pagine a giro (~1.200 richieste/giorno) per colpa del margine di 2 h, e un segnale gratuito di motivazione del venditore (chi riposiziona) viene buttato. | confronto DB ↔ hades **[misurato]** |
| F4 | **Il circuito di apprendimento è vuoto.** 0 affari in pipeline, 0 riparazioni registrate. Ogni margine mostrato è una stima su *prezzi chiesti*: mai confrontata con un prezzo pagato o incassato. | tabella `deals` **[misurato]** |
| F5 | **Non esiste uno strato di serie storiche.** `market_trends` è per *target* (concetto del vecchio cecchino), vuota, con `ON DELETE CASCADE`; il deprezzamento è solo trasversale; i modelli di prezzo si ricalcolano in memoria ogni 15 min e si buttano. | schema DB **[misurato]** |
| F6 | **Due macchine che si alternano.** PC spento alle 17:15, Mac acceso a sere alterne, dump e merge a mano (anche "al contrario"): niente inventario notturno quando il PC è spento, e ore di sessione spese a spostare dati invece che a creare valore. | sessioni 2–5/10 |

## 1. Il gap competitivo — cosa non sfruttiamo

In ordine di impatto atteso sul margine reale (ragionamento, da validare coi dati):

1. **Profitto atteso per ora di lavoro, non margine per pezzo.** Il collo di
   bottiglia di chi compra e ripara da solo è il *tempo* (contatto, viaggio,
   riparazione, vendita), non l'elenco di occasioni. Ordinare per
   `margine netto × P(riparazione riuscita) × P(ancora disponibile) ÷ ore`,
   con ore = viaggio (distanza: c'è da oggi) + minuti di riparazione (E2) +
   vendita. Cambia cosa compri: un +60 € a 5 km batte un +90 € a 80 km.
2. **Valore donatore ("per ricambi", lotti).** Oggi un iPhone "per ricambi" o
   con scheda madre morta vale 0 (invendibile). Per chi ripara è un donatore:
   schermo, batteria, fotocamere, scocca hanno un prezzo di listino che
   abbiamo già (listini Apple e aftermarket). Il privato lo svende. Valore
   donatore = Σ parti presumibilmente sane × prezzo aftermarket × sconto
   usato. Stessa logica per i lotti ("lotto 5 iPhone rotti"), che oggi
   scartiamo perché nominano più modelli.
3. **Emivita degli affari = concorrenza misurata.** Ogni annuncio segnalato
   come affare si ricontrolla ogni 10 minuti finché sparisce. Ne esce, per
   segmento, quanto dura un affare: dove la nostra latenza basta (durano ore)
   e dove no (spariscono in 5 minuti: inutile inseguirli). Costa decine di
   richieste al giorno. È il C6 della release, con risoluzione minuti invece
   che giorni.
4. **Il lato vendita.** Il sistema ottimizza solo l'acquisto. Il margine si fa
   anche vendendo: prezzo di pubblicazione consigliato per vendere in N
   giorni (curva prezzo→giorni + posizione nel pool), quando ribassare, quanti
   pezzi tenere per variante (profondità del mercato = venduti a settimana a
   quel prezzo: oltre ti fai concorrenza da solo).
5. **Segnali di motivazione gratuiti ignorati.** Riposizionamenti (F3),
   giorni online senza ribasso, ripubblicazioni (l'identità la calcoliamo già),
   ora e giorno di pubblicazione. Oggi usiamo solo i ribassi.
6. **Dati proprietari di transazione: l'unico vantaggio non copiabile.** Ogni
   contatto, offerta ed esito registrato, anche "sfumato" con il prezzo
   offerto. Dopo 30–50 affari: fattore di trattativa reale per segmento,
   probabilità che il venditore accetti −X%, tasso di riuscita delle
   riparazioni, costi veri. Condizione: **frizione zero**, cioè registrazione
   da Telegram in due tocchi (bottoni sotto l'alert), non dalla dashboard.
7. **Un prezzo d'uscita garantito.** Il riferimento di rivendita è il prezzo
   *chiesto* su Subito, né realizzato né garantito. Le quotazioni di
   riacquisto dei servizi di permuta e ricondizionamento sono un pavimento
   immediato: se prezzo + riparazione < quotazione, l'arbitraggio è quasi
   senza rischio. **Da verificare** quali quotazioni sono consultabili gratis
   e nel rispetto dei termini di servizio prima di costruirci sopra.
8. **Differenziali geografici (solo auto).** Indice di prezzo per regione e
   generazione, ora che abbiamo le coordinate: comprare dove costa meno, al
   netto del viaggio. Per gli iPhone la spedizione rende il mercato nazionale:
   valore basso.

Già solido, da non rifare: valore equo per variante, rischio anti-truffa,
costi di riparazione a due colonne, costi d'acquisto auto, copertura ≥ 99%.

## 2. Resilienza e dati

### Lo scraper in produzione per anni

1. **Un nodo unico, sempre acceso, con IP residenziale (A5).** È il
   prerequisito di tutto il resto: inventari notturni, alert, emivita. Un
   mini PC o un vecchio portatile a casa. I server gratuiti in datacenter
   hanno IP che i sistemi anti-bot trattano in modo più severo: non
   verificato per Subito, si misura solo se si vuole tentare.
2. **Un governatore del budget di richieste.** Oggi ogni job chiede il turno
   al pacer quando vuole e nessuno sa il totale: `scrape_runs` registra solo
   gli sweep. Stima di oggi ≈ 4–5k richieste al giorno (sweep auto ~1.200,
   sweep iPhone ~290, inventario iPhone ~520 + verifiche, fetta auto ~1.400).
   Serve: contatore per job, quote, **priorità** (alert > ricontrollo affari >
   sweep > inventario > verifiche) e taglio automatico dei lavori a bassa
   priorità ai primi segnali (403, reset TLS come quelli di oggi).
3. **Allarmi di deriva del formato.** Se Subito cambia un campo (`/car`,
   `geo`, `dates`) il parsing produce valori vuoti in silenzio. Soglie sul
   cruscotto qualità (es. dati strutturati < 80% sugli ultimi 1.000
   annunci) → allarme ops; più una sentinella oraria che rilegge un annuncio
   noto e confronta i campi.
4. **Raccolta e API in processi separati.** Oggi una migrazione lanciata dal
   backend di sviluppo ha ucciso l'inventario del raccoglitore. In compose:
   servizio `collector` (scheduler) e `api` (sola lettura, ricostruibile a
   piacere), stessa immagine. Oggi esiste solo come `docker run` a mano.
5. **Ripresa dei giri lunghi.** L'inventario salva pagina per pagina ma, se
   interrotto, ricomincia da capo. Checkpoint per fascia in `app_settings`.
6. **Conservazione dei dati.** Le auto crescono di ~13.000 righe al giorno,
   con descrizioni e identificativi dei venditori. Eliminare descrizione e
   `seller_id` N giorni dopo la sparizione contiene la crescita e applica i
   principi di minimizzazione e limitazione della conservazione (GDPR, art. 5,
   par. 1, lett. c ed e).

### Il database per le serie storiche

Oggi: righe mutabili (prezzo sovrascritto, `updated_at` = ultima vista),
`price_history` solo per i cambi di prezzo. Goal, tutto in Postgres puro
(niente TimescaleDB: i volumi sono migliaia di righe al giorno):

- **`listing_events`** in sola aggiunta: comparso, prezzo, riposizionato,
  sparito, ricomparso, fuso. Ricostruisce qualunque storia ed è la base per
  sopravvivenza e validazioni (G11/G12).
- **`market_daily`** (variante/generazione × giorno): attivi, nuovi, spariti,
  p25/p50/p75 del prezzo, giorni online mediani.
- **`price_models`** (variante × giorno): coefficienti, campione, errore. I
  modelli si calcolano una volta al giorno e si leggono, invece di rifarli in
  memoria ogni 15 minuti. Il deprezzamento diventa una serie vera (come cambia
  il valore di un 13 Pro 128 settimana dopo settimana) e la stagionalità
  (keynote di settembre) si misura invece di ipotizzarla.
- Via `market_trends` e `products`: concetti del vecchio cecchino per target.

## 3. Latenza: alert in tempo reale

**Bilancio di oggi (iPhone):** ~6 min di indicizzazione (non riducibile) +
7,5 min medi di attesa del giro + download foto + arricchimento a fine giro ≈
**14 min dalla pubblicazione, di cui ~8 nostri**. Per le auto, ~21.
**Goal: ≤ 1 minuto nostro (p95 ≤ 2) dopo l'indicizzazione.**

Subito non offre push né websocket: "tempo reale" significa interrogare la
testa della coda in modo economico e decidere subito. Niente Kafka, Redis o
microservizi: una coda `asyncio` nello stesso processo basta.

```
 testa (pagina 1 ogni 30–60 s) ──► nuovi davvero? ──► corsia veloce ──► Telegram (foto dal CDN)
        │                          (URL già visti)     NLP + modelli          │
        │                                              in cache (ms)          ▼
 sweep ogni 15–30 min (rete di sicurezza, margine 20 min)          salvataggio, foto, arricchimento
 ricontrollo affari segnalati e salvati (emivita, ribassi)         (dopo, in background)
```

1. **Testa della coda** separata dallo sweep: ogni 30–60 s solo pagina 1
   (100 annunci). Per gli iPhone la pagina copre ~50 minuti, quindi nessun
   buco. **[misurato]**
2. **Corsia veloce:** parse + NLP + valutazione con i modelli già in cache →
   decisione → Telegram *subito*, con la foto presa dal link pubblico del CDN
   di Subito. Salvataggio, download delle foto e arricchimento completo
   avvengono dopo.
3. **Sweep come rete di sicurezza**, con margine di 20 minuti invece di 2
   ore: il ritardo di indicizzazione misurato è ~6. Recupera i persi senza
   rileggere ore di riposizionamenti. Quelli moderati tardi li prende
   l'inventario notturno.
4. **Budget:** pagina 1 ogni 60 s per iPhone e auto = 2.880 richieste al
   giorno, compensate dal taglio del margine dello sweep (~−1.000 solo sulle
   auto). Totale circa invariato, con il governatore che dà priorità alla
   testa.
5. **Azione in un tocco.** La gara si vince al primo messaggio credibile al
   venditore, non alla notifica. L'alert porta il link diretto (apre l'app
   Subito), un messaggio d'offerta pronto da copiare con il tetto, e bottoni
   per registrare l'esito (§1.6).
6. **Misura:** pubblicazione→alert e indicizzazione→alert, p50/p95, nel
   cruscotto (G13 c'è già), più gli alert falliti, che devono essere 0.

## 4. Tagli: cosa smettere di costruire

1. **La raccolta di tutte le auto (537k) sullo stesso nodo e IP.** È la
   complessità più cara introdotta: inventario a rotazione su 4 notti, venduti
   euristici a fine ciclo, foto ridotte, feed da scalare, ~2.500 richieste al
   giorno in concorrenza con gli alert iPhone, ~13.000 righe al giorno. Tutto
   per un utente che non l'ha ancora usata. **Taglio:** in produzione
   `AUTO_FULL_CATEGORY=false` finché l'amico non la usa davvero. Poi due
   strade: raccolta limitata ai suoi criteri lato server (fascia di prezzo,
   marche), oppure un'istanza sulla sua macchina con il suo IP. Il codice
   resta: è un interruttore.
2. **Due macchine e il merge.** Merge normale, merge al contrario, dump
   quotidiani: esistono solo perché manca un nodo unico. Con A5 spariscono.
3. **Deal Score 0–100.** Media di una decina di segnali con pesi scelti a
   mano, opaca, usata come soglia degli alert. Va sostituito dal profitto
   atteso per ora (§1.1): una cifra in euro che si capisce e si verifica.
4. **Sei motori di prezzo.** Pool per variante, venduti, matrice riparazioni,
   `max_bid`, modelli auto, deprezzamento e magazzino per variante: regole
   diverse, rischio di numeri incoerenti tra schermate. Va sostituito da un
   servizio di prezzo per verticale che scrive `price_models`/`market_daily`;
   tutto il resto legge da lì.
5. **Schermate senza decisione.** Market Intelligence iPhone (trend per
   target, premio memoria, distribuzioni), Tempo di vendita per colore,
   classifica venditori, pausa/ripresa job in Automations: si congelano, senza
   altro lavoro. Si tengono feed, matrice riparazioni, pipeline e qualità del
   dato.
6. **Statistica avanzata senza eventi.** Kaplan–Meier con entrata ritardata,
   classificazione venduto/ritirato, liquidità 0–100, correzioni dopo 3
   riparazioni: corretti, ma con zero eventi. Nessuna nuova sofisticazione
   finché non c'è un dato vero da spiegare (4–6 settimane di inventari, primi
   30 affari).
7. **AI su tutti gli annunci.** Si usa solo sui candidati (≈ il 2–5% che
   passa il filtro di prezzo o guasto), su richiesta. Meno carico, e latenza
   compatibile con la corsia veloce.
8. **Foto per tutto.** Archivio storico degli iPhone (annunci per lo più
   spariti) e prima foto di 537k auto: costo marginale basso, ma nessun
   vantaggio. Il valore sta nelle foto degli annunci candidati, salvati e in
   pipeline.
9. **Residui del vecchio cecchino per target.** `run_sniper_all_products`
   per il tech, Garbage Collector auto, `products`/`market_trends`,
   `target_models` come chiave statistica: buona parte delle 1.221 righe di
   `tasks.py` è dell'era prima dello sweep.
10. **`page.tsx` da 6.189 righe.** Non è una funzione da tagliare ma il
    sintomo più chiaro del vibe coding: ogni modifica costa di più e rompe di
    più. Si spezza per schermata solo quando la si tocca.

**Da non fare, anche se tenta:** proxy a pagamento, browser headless, code
o broker esterni, microservizi, TimescaleDB, modelli ML pesanti prima di
avere 30 affari veri.

## 5. Le tappe della Goal Version

| Tappa | Contenuto | Durata indicativa |
|---|---|---|
| **P0** | Fix alert con foto (link CDN + ripiego testo); nodo unico sempre acceso con `collector`/`api` separati; margine dello sweep a 20 min; auto complete spente in produzione; esiti registrabili da Telegram | giorni |
| **P1** | Testa della coda + corsia veloce + misura latenza; governatore del budget; allarmi di deriva; ricontrollo affari (emivita) | 1–2 settimane |
| **P2** | Profitto atteso per ora; valore donatore e lotti; segnale riposizionamenti; prezzo di vendita consigliato; `listing_events` + `market_daily` + `price_models` | 2–4 settimane |
| **P3** | Con i dati: fattore di trattativa e P(accetta) dalla pipeline, riuscita delle riparazioni, stagionalità, pavimento di riacquisto (se le fonti sono consultabili) | 4–8 settimane |

### Stato al 2026-10-05 sera

**P0, fatto in codice** (commit `7bd66d3`):
- alert con la foto del CDN, ripiego sul testo, consegna reale registrata;
- bottoni ed esiti da Telegram;
- margine dello sweep a 20 minuti;
- `collector` e `backend` separati in compose.

**P0, manca:**
- il nodo unico (A5), che è hardware;
- spegnere le auto complete in produzione. Rimandato per scelta: si decide con i
  numeri della riga "Richieste oggi" (vedi MERGE-DB, passaggio del 5/10).

**P1, fatto** (commit `7bd66d3`, `86077fb`, `90edfa4`, `97f1a10`, `cfe4bc6`):
- testa della coda ogni 60 s, che salva senza foto e notifica nello stesso giro;
- ricontrollo degli affari con la metrica dell'emivita; i candidati si
  registrano anche senza Telegram;
- allarmi di deriva orari;
- governatore: contatori per job in `request_log` più pausa dei lavori bassi
  con la rete instabile o dopo un blocco;
- messaggio d'offerta pronto da copiare nell'alert (§3.5): si tocca, si copia,
  si incolla al venditore.

Primo giro reale sul PC, alle 12:50: +8 iPhone e +100 auto alla prima lettura
della testa.

Due correzioni dai primi dati:
- **Subito indicizza a ondate** (~ogni 10 minuti). Un'ondata di auto supera
  spesso la pagina 1, quindi la testa legge anche la 2 e la 3 quando la 1 è
  tutta nuova.
- **Gli alert auto senza criteri del compratore erano ~2.500 al giorno**
  (47 in 27 minuti). Ora serve almeno un criterio e un margine oltre l'errore
  tipico del modello.

**P1, manca:**
- quote giornaliere per job: si fissano dopo una settimana di `request_log`,
  non a occhio;
- antiripubblicazione con pHash per gli annunci salvati dalla testa. La foto
  arriva dopo, quindi per ora vale solo il controllo venditore + variante +
  prezzo.

**P2, iniziato il 5/10:**
- `listing_events` (migrazione 26). I trigger nel DB registrano comparso,
  prezzo, sparito, ricomparso, ripubblicato e fuso su ogni percorso di
  scrittura; l'applicazione registra i riposizionamenti. Storia di partenza:
  105k comparse.
- Segnali dell'annuncio nel dettaglio: riposizionato N volte, ripubblicato,
  ribassato più volte, fermo da settimane (§1.5).
- Profitto atteso per ora (§1.1), con l'ordinamento "€/ora" e i tempi
  modificabili in Impostazioni.
- Rinviati:
  - valore donatore: i listini aftermarket sono bassi e il valore di una
    parte originale usata non è verificabile;
  - lato vendita: servono i venduti dei telefoni, che sul DB del PC sono
    ancora 0;
  - `market_daily` e `price_models`: si ricostruiscono dagli eventi.

### Come si sa che ci siamo

- Latenza indicizzazione→alert **p95 ≤ 2 min**; alert falliti **= 0**.
- **≥ 1 affare a settimana** registrato dall'alert all'incasso.
- Errore stima ↔ realizzo **≤ 10%** dopo 30 affari chiusi.
- Copertura ≥ 95% e zero annunci persi per 14 giorni (già in RELEASE).
- **Zero ore al mese** spese a spostare o unire dati tra macchine.
