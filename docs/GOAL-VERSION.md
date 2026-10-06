# Goal Version — dove deve arrivare FlipRadar e a che punto è

> **Documento unico** (dal 2026-10-05) per obiettivo, release e visione del
> prodotto: riunisce quello che prima era diviso fra GOAL-VERSION, RELEASE,
> ROADMAP, VISIONE-IPHONE e VISIONE-AUTO. Le richieste già completate della
> vecchia roadmap, che non servono più a decidere, sono in
> [STORICO.md](STORICO.md); come funziona il sistema oggi è negli altri
> documenti di `docs/` (architettura, dati, deploy, procedure).
>
> Le §0–5 sono l'analisi del 2026-10-05 su tutto il codice (≈12.800 righe
> backend, 7.800 frontend, 24 migrazioni, 40 script) e su tutti i documenti di
> progetto: ogni affermazione marcata **[misurato]** è stata verificata sul
> sistema vivo quel giorno; il resto è ragionamento, dichiarato come tale.
> Le §6–8 sono le liste di controllo (criteri della release, definizione di
> "fatto" per verticale), la §9 il backlog aperto e le idee. I riferimenti nel
> codice ("Goal Version §1.3", "criterio B5", "§8.5") puntano a queste sezioni.

## Indice

- [Il nord, in una riga](#il-nord-in-una-riga)
- [Il business e i principi](#il-business-e-i-principi)
- [0. Diagnosi](#0-diagnosi-sei-fatti-che-cambiano-le-priorità)
- [1. Il gap competitivo](#1-il-gap-competitivo--cosa-non-sfruttiamo)
- [2. Resilienza e dati](#2-resilienza-e-dati)
- [3. Latenza](#3-latenza-alert-in-tempo-reale)
- [4. Tagli](#4-tagli-cosa-smettere-di-costruire)
- [5. Le tappe, lo stato, come si sa che ci siamo](#5-le-tappe-della-goal-version)
- [6. Release v1: criteri di "pronto" e distanza](#6-release-v1--criteri-di-pronto-e-distanza)
- [7. Verticale iPhone: definizione di "fatto"](#7-verticale-iphone--definizione-di-fatto)
- [8. Verticale auto: definizione di "fatto"](#8-verticale-auto--definizione-di-fatto)
- [9. Backlog aperto e idee](#9-backlog-aperto-e-idee)

## Il nord, in una riga

Nell'usato vince chi **vede l'occasione per primo, sa il margine vero prima
degli altri, manda per primo un'offerta credibile e impara dai propri
affari**. Tutto ciò che non accorcia uno di questi quattro tempi o non rende
più vero il margine è rumore.

## Il business e i principi

### Il business che la versione finale deve servire

Comprare **iPhone rotti o difettosi** su Subito, ripararli (con ricambi
aftermarket o originali) e rivenderli. In secondo piano: segnalare i **sani
sottoprezzati**, rari ma da non perdere. Dal 2026-10-05 l'ambito è **iPhone 12
e successivi** (`IPHONE_MIN_GEN`): sotto c'è poco giro e poco margine.

Per ogni annuncio il programma deve rispondere con numeri affidabili a:

1. **Che guasto ha, e si ripara?** (tipo di guasto, riparabile / a rischio / invendibile)
2. **Quanto costa ripararlo?** (ricambio aftermarket o Apple + manodopera)
3. **A quanto lo rivendo riparato, e in quanto tempo?**
4. **Quanto posso pagarlo al massimo?** (tetto d'acquisto, già al netto di tutto)
5. **È sicuro comprarlo?** (truffa, iCloud, venditore)

E per il mercato: **dove conviene cacciare** (quali modelli × guasti rendono
di più e girano in fretta).

Le stesse domande, dette in modo valido per ogni verticale (così le usa anche
quello auto, §8): per ogni annuncio e per ogni modello il sistema deve
rispondere a 5 domande operative, **quanto vale davvero · quanto posso
pagarlo · quanto e quando lo rivendo · di chi mi fido · è sicuro comprarlo.**
Coperte tutte, con dati affidabili e visibili in UI, un verticale è completo.

Il verticale auto (§8) serve a un amico che fa flipping e compravendita.

### Principi

- 🧭 **Niente servizi a pagamento (dal 2026-10-02).** Il proxy residenziale
  IPRoyal è dismesso (crediti finiti, nessun rinnovo). Si scrapa in connessione
  diretta a un ritmo lento, restando sotto la soglia di blocco invece di
  aggirarla. Obiettivo di sufficienza: **raccogliere più annunci al giorno di
  quanti ne vengano pubblicati** nelle categorie seguite; oltre quello la
  velocità non conta. Ogni nuova dipendenza deve essere gratuita/self-hosted.
- **Da non fare, anche se tenta:** proxy a pagamento, browser headless, code o
  broker esterni, microservizi, TimescaleDB, modelli ML pesanti prima di avere
  30 affari veri (dettaglio in §4).

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
   richieste al giorno. È il criterio C6 della release (§6), con risoluzione
   minuti invece che giorni.
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
   resta: è un interruttore. *(Decisione del 2026-10-05 sera: per ora si
   tiene accesa; se arrivano blocchi, si passa alla via di mezzo, cioè solo
   gli annunci nuovi delle auto senza inventario a rotazione, vedi §5.)*
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
   compatibile con la corsia veloce. *(Superato il 6/10: sul Mac `gemma4:e4b`
   legge circa 5.000 annunci al giorno, quindi si analizzano tutti gli iPhone,
   in ordine di utilità — prima i candidati e i sottoprezzati, criterio B5.)*
8. **Foto per tutto.** Archivio storico degli iPhone (annunci per lo più
   spariti) e prima foto di 537k auto: costo marginale basso, ma nessun
   vantaggio. Il valore sta nelle foto degli annunci candidati, salvati e in
   pipeline. *(Non applicato: l'utente vuole tutte le foto.)*
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

- il nodo unico (A5): dal 6/10 raccoglie solo il Mac; restano niente
  sospensione in carica e avvio automatico di Docker (criterio A5, §6);
- spegnere le auto complete in produzione: confermato di **tenerle accese**
  (decisione del 5/10 sera). Se arrivano blocchi, la via di mezzo è
  `SCHEDULER_SKIP=inventory_auto,inventory_watchdog_auto` nel `.env` (vedi
  MERGE-DB, passaggio del 5/10).

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
- antiripubblicazione con pHash per gli annunci salvati dalla testa. La
  fusione notturna (venditore + variante + prezzo) copre già chi ripubblica
  dallo stesso account; la foto servirebbe per gli account nuovi, e la sua
  precisione va prima misurata a mano (G12).

**Ambito e riconoscimento (5/10 pomeriggio):**

- **iPhone dal 12 in su** (`IPHONE_MIN_GEN`): sotto c'è poco giro e poco
  margine. 11.177 annunci più vecchi e 272 non iPhone (altri marchi,
  accessori) sono in archivio, non cancellati. Il filtro modelli passa da 859
  voci (809 erano titoli non riconosciuti) a 29 modelli veri.
- **Riconoscimento dei guasti misurato:** le regole trovano il 48% dei guasti
  reali, con il 91% di precisione (serie di verifica, 99 annunci). Più di metà
  dei rotti passa per sana: il collo di bottiglia è l'AI (B5 sul Mac), non
  altre regole. Intanto l'AI legge prima i candidati, poi gli annunci sotto
  l'80% della mediana del modello, poi i modelli non riconosciuti. La scheda
  avvisa quando un annuncio non è ancora stato letto dall'AI.
- **Il 6/10, sul Mac:** modello AI scelto su misure (`gemma4:e4b`, F1 0,79) e
  acceso su tutti gli iPhone attivi, nello stesso ordine di utilità. Nella
  condizione entrano solo i guasti dove l'AI è affidabile (criteri B3–B5, §6).
- **Rivendita dai venduti:** un modello passa alla stima dai venduti con
  almeno 5 vendite pulite. Il 5/10 erano 0 venduti al mattino; nel pomeriggio
  254, con 19 varianti già sopra soglia.

**Resilienza, fatto il 5/10 pomeriggio:**

- **Verifiche dei venduti in coda nel DB**, a pezzi da 50 (§2.5, la parte più
  lunga dell'inventario). L'inventario iPhone del 5/10 ha trovato 3.565
  candidati: circa 6 ore di verifiche. Prima i rimossi si marcavano solo
  alla fine, e spegnere la macchina buttava tutto. Ora ogni pezzo resta fatto
  e la coda viaggia nel dump. Nel primo pezzo, 46 venduti su 50 candidati.
  Il giro dell'inventario (circa 2 ore) riparte invece ancora da capo.
- **Raccolta del PC sul `collector` di compose** dalle 14:02 (prova generale
  della sera), con `SCHEDULER_SKIP` per lasciare la fetta auto al Mac.
- **AI prima sui candidati** (§4.7): segnalati, salvati, in pipeline; poi i
  più recenti.
- **Latenza di scoperta solo sui freschi**: mediana 3,1 minuti dalla
  pubblicazione; i tardivi, recuperati dall'inventario, contati a parte.
- **Pannello "Obiettivi della Goal Version"**: le metriche qui sotto misurate
  dal vivo. Il 5/10 sono 2 su 5: latenza p95 0,1 min, copertura 99,9%. Gli
  altri aspettano Telegram e i primi affari in pipeline.

**P2, iniziato il 5/10:**

- `listing_events` (migrazione 26). I trigger nel DB registrano comparso,
  prezzo, sparito, ricomparso, ripubblicato e fuso su ogni percorso di
  scrittura; l'applicazione registra i riposizionamenti. Storia di partenza:
  105k comparse.
- Segnali dell'annuncio nel dettaglio: riposizionato N volte, ripubblicato,
  ribassato più volte, fermo da settimane (§1.5).
- Profitto atteso per ora (§1.1), con l'ordinamento "€/ora" e i tempi
  modificabili in Impostazioni.
- Storia dell'annuncio (comparso, ribassi, riposizionamenti, sparito) nella
  riga espansa del feed.
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
- Copertura ≥ 95% e zero annunci persi per 14 giorni (criteri A2 e A3, §6).
- **Zero ore al mese** spese a spostare o unire dati tra macchine.

## 6. Release v1 — criteri di "pronto" e distanza

> Bozza del 2026-10-02, rivalutata lo stesso giorno dopo un audit completo
> della gestione dati (gruppo G). Serve da **punto di riferimento**: cosa deve
> fare il programma per essere "pronto" per il business (vedi *Il business e i
> principi*), e quanto manca. Si rivaluta spesso (a ogni giro di sviluppo) e
> può crescere: le idee nuove vanno nella §9, a meno che non blocchino il
> business. Le priorità aggiornate sono le tappe della §5.

Stato: ✅ fatto · 🔧 c'è ma non basta / va misurato · ◻️ manca

### A. Raccolta — vedere tutto il mercato, gratis

| # | Criterio | Stato |
|---|---|---|
| A1 | Nessun servizio a pagamento; ritmo sotto la soglia di blocco, stop automatico sui 403 | ✅ |
| A2 | Copertura ≥ 95% della ricerca che Subito dichiara (annunci letti / dichiarati, dall'inventario) | ✅ 99,95% (51.643 letti su 51.669, inventario del 2026-10-02, completo) · 99,9% il 2026-10-05 · da mantenere ogni notte |
| A3 | Zero annunci persi tra un giro e l'altro (`gaps` = 0 per 14 giorni di fila) | 🔧 da osservare |
| A4 | Venduti/rimossi rilevati ogni notte (inventario + verifica) | ✅ codice: esito sempre registrato, allarme se interrotto/incompleto, recupero automatico se il PC era spento all'1:30 · dal 5/10 verifiche in coda nel DB, riprese dopo un riavvio · 🔧 primi dati: 520 venduti marcati il 5/10 |
| A5 | Gira da solo 30 giorni senza interventi, su UNA macchina sempre accesa | 🔧 dal 2026-10-06 raccoglie solo il **Mac** (`collector`, DB unico, foto unite, password DB non di default); il PC fa solo da dashboard · da fare sul Mac: niente sospensione in carica (`sudo pmset -c sleep 0`), Docker Desktop all'accesso, coperchio aperto · conta dei 30 giorni dal 6/10 |

### B. Qualità del dato — sapere cosa c'è nell'annuncio

| # | Criterio | Stato |
|---|---|---|
| B1 | Modello riconosciuto ≥ 97% degli annunci attivi | ✅ 97,8% (anche dalla descrizione se il titolo dice solo "iPhone") |
| B2 | Memoria letta in ≥ 95% degli annunci che la scrivono (prima: "≥ 85% di tutti") | ✅ ~97% di chi la scrive · 80,1% di tutti: il ~18% degli annunci non riporta alcun taglio, nessuna regola o AI lo può leggere dal testo |
| B3 | **Guasto classificato per tipo** (tassonomia in `services/defects.py`) con F1 ≥ 0,90 sulla serie di **verifica** etichettata (`scripts/eval_guasti.py`) | 🔧 regex v2: precisione 0,91 ma richiamo 0,48 (F1 0,62) su annunci mai visti (rimisurato il 5/10) · AI `gemma4:e4b` (6/10): richiamo 0,76 ma precisione 0,50 in verifica (immagina schermo/scocca/"altro" su telefoni sani) → nella condizione entrano solo i guasti dove l'AI è affidabile (face-id, fotocamera, audio, tasti, scheda madre, acqua, non si accende, bloccato); gli altri restano nell'analisi visibile · prossimo passo: prompt contro le allucinazioni, tarato sulla serie di sviluppo |
| B4 | **Parti non originali** riconosciute (display/batteria già sostituiti: pesano sul prezzo) | 🔧 regex: F1 0,77 in verifica · AI `gemma4:e4b`: F1 0,93 su tutte le 244 (regex 0,87) → l'AI le aggiunge |
| B5 | Modello AI locale scelto **su misure**, che copre tutti gli annunci rilevanti | ✅ misurati sul Mac (M4, 24 GB, senza ventola) il 6/10 con lo stesso prompt della produzione: `gemma4:e4b` F1 0,79 · 13,5 s/annuncio; `qwen3.5:4b` 0,60 · 16 s; `qwen3.5:9b` 36 s e `gemma4:12b` 48 s/annuncio (troppo lenti per tutto l'archivio); MLX +15% soltanto. In produzione `gemma4:e4b` su **tutti** gli iPhone attivi (prima candidati e sottoprezzati), ~5.000 annunci al giorno al ritmo di default (14 s l'uno, 80% del tempo): candidati e sottoprezzati in poche ore, l'intero archivio (~39.000) in ~2 settimane insieme ai ~2.200 nuovi al giorno |

### C. Metriche per il business

| # | Criterio | Stato |
|---|---|---|
| C1 | Costi ricambi per modello in due colonne (Apple con credito di reso, aftermarket) | ✅ |
| C2 | **Sconto rotto vs sano per modello × guasto** (non un unico "rotto") | ✅ matrice Riparazioni |
| C3 | **Prezzo di rivendita del riparato** (con parti non originali), misurato sul mercato | ✅ schermo non originale −15,6%, batteria −2% (misurati) |
| C4 | Tempo di vendita onesto (Kaplan–Meier), venduto/ritirato/scaduto separati | ✅ codice · 🔧 servono 4–6 settimane di venduti |
| C5 | **Matrice opportunità modello × guasto**: prezzo tipico d'acquisto, riparazione, rivendita, margine, giorni, annunci/settimana | ✅ schermata Riparazioni (giorni di vendita: con i venduti) |
| C6 | Concorrenza sui rotti: quanto in fretta spariscono quelli sottoprezzati | 🔧 dal 5/10 emivita degli affari (§1.3) nel cruscotto · matura coi dati |

### D. Decisione sul singolo annuncio

| # | Criterio | Stato |
|---|---|---|
| D1 | Tetto d'acquisto per i rotti = rivendita del riparato − ricambio − manodopera − magazzino − margine | ✅ (corretto anche il doppio conteggio del guasto) |
| D2 | Rischio (iCloud, truffa, venditore) | ✅ |
| D3 | **Alert Telegram per le opportunità di riparazione** | ✅ soglia margine netto in Impostazioni (default 60€) |
| D4 | Sani sottoprezzati segnalati comunque | ✅ |

### E. Imparare dalle proprie riparazioni

| # | Criterio | Stato |
|---|---|---|
| E1 | Pipeline P&L con stima vs reale | ✅ |
| E2 | Per ogni riparazione: pezzo usato, costo reale, tempo, esito (riuscita/fallita), prezzo di vendita | ✅ pipeline: stima all'aggancio + riparazione reale |
| E3 | I dati reali correggono costi (C1), rivendita (C3) e il tasso di fallimento dei "non si accende" | ✅ codice: ricambi corretti dal rapporto reale/listino da 3 riparazioni, riuscita per guasto nella scheda · 🔧 servono riparazioni registrate; la rivendita del riparato resta misurata sul mercato (C3) |

### F. Operatività

| # | Criterio | Stato |
|---|---|---|
| F1 | Migrazioni automatiche all'avvio | ✅ |
| F2 | Backup automatico del DB (e delle foto) con verifica di ripristino | ✅ servizio `backup`: dump notturno ripristinato in un DB di prova, foto in copia speculare, esito nel cruscotto e allarme |
| F3 | Allarmi di sistema (blocco, giro down) | ✅ |
| F4 | Cruscotto qualità del dato | ✅ (+ esito inventario, coda foto, backup) |
| F5 | Sicurezza minima: DB e API raggiungibili solo dalla macchina, password DB non di default | ✅ porte su 127.0.0.1 · ◻️ password DB ancora quella di default: va cambiata (comando in [RACCOLTA-SU-QUESTO-PC.md](RACCOLTA-SU-QUESTO-PC.md)) |
| F6 | Foto di tutti gli annunci (anche archivio) | ✅ backfill dalla CDN immagini, a lotti, sicuro sui blocchi · 🔧 ~45k annunci in coda, ~13 h (2/10) |

### G. Affidabilità del dato (audit 2026-10-02)

Senza questi, le metriche C4/C5 e gli alert possono essere *precisi ma
sbagliati*. Corretti il 2026-10-02:

| # | Problema trovato | Stato |
|---|---|---|
| G1 | Ripubblicazioni: un negozio che vende un pezzo e ne carica uno uguale "cancellava" la vendita; il pHash fondeva annunci di venditori diversi con la stessa foto di catalogo | ✅ serve lo stesso venditore; chi ha 2 pezzi uguali online insieme è un negozio e non si abbina |
| G2 | Kaplan–Meier senza entrata ritardata: lo stock trovato già vecchio (backfill) avrebbe allungato i tempi di vendita per mesi | ✅ troncamento a sinistra (entrata = età quando l'abbiamo visto) |
| G3 | "Scaduto dopo un anno": falso, 1.528 iPhone di privati online da 12–21 mesi | ✅ soglia a 2 anni; sotto decidono le regole sul ritirato |
| G4 | Inventario: pagina vuota a metà fascia = "completo"; errori diversi dal blocco senza traccia; job notturni in UTC (2h dopo il previsto); Motore Notturno a orario fisso anche con inventario in corso | ✅ completezza per annunci letti, esito e allarme sempre, fuso Europe/Rome, Motore Notturno a valle dell'inventario |
| G5 | Annunci in moderazione dietro il segnalibro dello sweep (margine 10 min) | ✅ margine 2 h (2/10), poi 20 min con la testa della coda (5/10, §3.3) · 🔧 da misurare: nuovi recenti trovati solo dall'inventario |
| G6 | Verifiche delle pagine annuncio fuori dal pacer anti-blocco | ✅ passano dal pacer globale |
| G7 | Corsa sweep/inventario sull'insert (salta l'intero lotto) | ✅ `on conflict do nothing` |
| G8 | Alert su valori equi da 3 prezzi chiesti | ✅ niente alert con confidenza bassa (< 6 campioni) |
| G9 | Matrice: volume contato solo sugli attivi (i rotti migliori spariscono in fretta e non contavano) | ✅ conta tutti i nati nella finestra |
| G10 | Cancellare un target cancellava lo storico dei suoi annunci (cascade) | ✅ migrazione 22: `on delete set null` |

Ancora da fare per la v1:

| # | Criterio | Stato |
|---|---|---|
| G11 | **"Venduto" validato**: un campione di sparizioni controllato a mano (pagina rimossa vs ancora online vs scaduta) per misurare la precisione di `is_removed` prima di fidarsi di C4 | 🔧 `scripts/sample_removals.py` pronto (55 URL da aprire, ~20 min) · da fare dopo un inventario completo. Venduto vs ritirato resta un'euristica: Subito non lo dice |
| G12 | **Ripubblicazioni validate** su un campione etichettato (precisione/richiamo di pHash e venditore+variante), come per i guasti | 🔧 `scripts/sample_republish.py` pronto (70 coppie, ~30 min) · da fare sul Mac dopo una settimana di inventari, insieme a G11 |
| G13 | **Latenza annuncio → alert** misurata (p50/p95): nel business dei rotti vince chi arriva primo | ✅ misura nel cruscotto (scoperta, tardivi oltre 2h, alert) · ✅ dal 5/10 testa della coda ogni 60 s (alert nello stesso giro, foto dal CDN) ed emivita degli affari (quanto restano online dopo l'alert) · 🔧 alert solo con Telegram configurato: pulsanti di prova in Impostazioni |
| G14 | **Prezzo di realizzo ≠ prezzo chiesto**: fattore di trattativa dalle proprie compravendite, applicato a rivendita e tetto | ◻️ si attiva con la pipeline (come E3) |
| G15 | **Incertezza visibile**: campione accanto a ogni cifra di matrice, tetto e alert; matrice per memoria (il mix 64/128/256 differisce tra rotti e sani) | ✅ campione e celle fragili nella matrice, confidenza sul valore equo; margini della matrice col sano a parità di memoria (scheda e tetto lo erano già: valore equo per variante modello+memoria) |
| G16 | Unione dei DB PC+Mac senza false vendite (le sparizioni durante il fermo di una macchina) | ✅ ultimo merge il 2026-10-06 sul Mac (dump PC principale + vecchio Mac, foto comprese); con una sola macchina non servono altri merge · prima: merge del 2026-10-03 sul Mac (51.794 annunci tech) |

### Distanza (valutazione del 2026-10-02)

- **Fatto:** la base (A1, A4, B1, B2, C1, C2, C3, C5, D1–D4, E1, E2, F1–F4, F6) e
  l'affidabilità del dato G1–G10.
- **Sviluppo che manca, in ordine:**
  1. **A5 — una macchina sempre accesa.** È il collo di bottiglia: senza
     inventari ogni notte C4/C6/G11 non maturano mai. Deciso questo, i dati
     del PC si uniscono una volta e poi c'è un solo DB. *(Dal 6/10 il Mac:
     ultimo merge fatto, vedi A5 e G16.)*
  2. **G11 + G12** — validare venduto e ripubblicazioni su campioni a mano
     (mezza giornata di etichettatura, dopo una settimana di inventari).
  3. **B5 → B3/B4** — modello AI misurato sul Mac, poi guasti oltre le regex.
     *(B5 fatto il 6/10; B3 resta da migliorare: troppi guasti immaginati.)*
  4. **G13, G15** — latenza degli alert e incertezza visibile (fatti entrambi
     dal 5/10, vedi la tabella sopra).
- **Dati che solo tu puoi dare:** riparazioni registrate in pipeline (E3 si
  attiva da 3 riparazioni per ricambio).
- **Tempo che nessuno sviluppo accorcia:** venduti e tempi di vendita (C4, C6)
  diventano affidabili solo con **4–6 settimane** di inventari notturni.
  Conviene quindi spostare presto la raccolta su una macchina sempre accesa (A5).

Stima onesta: il programma è **usabile per decidere** oggi sui rotti con
guasto chiaro (schermo, batteria, scocca), con la matrice e il tetto
d'acquisto. È **v1** quando: A5 è risolto, ci sono 4–6 settimane di
inventari (C4/C6), venduto e ripubblicazioni sono validati (G11/G12) e il
modello AI copre il richiamo dei guasti (B3/B5). Il lavoro di sviluppo che
resta è poco; il tempo che resta è soprattutto **raccolta continua**.

### Come si misura il riconoscimento dei guasti

Due serie etichettate a mano in `scripts/data/`:

- **sviluppo** (145 annunci): usata per scrivere le regex → i suoi numeri sono
  ottimisti per costruzione (F1 0,98);
- **verifica** (99 annunci, campionati per fascia di prezzo): **mai** usata per
  correggere le regole → è il numero onesto. Se le si usa per correggere,
  perde valore: in quel caso si etichetta una serie nuova.

`python scripts/eval_guasti.py --set verifica [--models a,b,c]` misura regex e
modelli AI con le stesse metriche. Dopo ogni miglioramento del riconoscimento:
`scripts/reparse_nlp.py --apply` lo rende retroattivo sull'archivio.

## 7. Verticale iPhone — definizione di "fatto"

> Inventario delle **schermate, analitiche e funzionalità** del verticale
> iPhone, con lo stato. ⚠️ *Rivalutazione 2026-10-02:* il business principale
> è comprare iPhone **rotti da riparare** e rivenderli; le schermate qui sotto
> coprono bene il mercato del *sano*, ma non ancora guasti per tipo, costi di
> riparazione reali e prezzo del riparato. Il riferimento per criteri e
> distanza è la §6; questa sezione resta come inventario delle funzioni. Quando
> (quasi) tutto qui è ✅, l'iPhone è "chiuso" e si passa alle **auto** (§8: più
> modelli/denominazioni/parametri → più complesse).

Stato: ✅ fatto · 🔧 parziale (c'è ma da rifinire / matura coi dati) · ◻️ da fare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

### 7.1 Feed / Live Sniper — *"cosa compro adesso"*

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
- ✅ **Costo di magazzino nel tetto d'acquisto**: il max bid sconta il
  deprezzamento che matura mentre il pezzo resta invenduto (curva della variante
  × giorni attesi di vendita). Senza, il tetto è ottimista proprio su ciò che
  gira lento. Voce dedicata nell'espansa.
- ✅ **Alert Telegram sui salvati** ⭐: un annuncio che segui ti avvisa a **ogni**
  ribasso, anche sotto la soglia minima di calo.
- ✅ Espansa: valore equo (fonte + affidabilità), **max bid**, offerta
  consigliata, **ROI/giorno**, ribasso, **venditore + profilo motivato**,
  margine netto post-riparazione (solo ricambio Apple), analisi AI, breakdown
  score, galleria + lightbox
- ✅ **Azioni sull'annuncio**: salva ⭐ / scarta 🗑 (nascondi) per riga,
  persistite (`triage`); viste Attivi / Salvati / Tutti.
- ✅ **Preset rapidi**: 🟢 compra ora, 🎯 motivati, 🔧 riparabili
- ✅ **Sort per ROI/giorno** (oltre a score/recenti/margine)
- ✅ Dal 2026-10-05: ordinamento **€/ora** (§1.1), segnali e storia
  dell'annuncio (§1.5), avviso quando l'annuncio non è ancora stato letto
  dall'AI, filtro modelli solo con i modelli veri dell'ambito.

### 7.2 Market Intelligence — *"cosa conviene / come si muove il mercato"* (anche HOME)

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

### 7.2b Tempo di vendita — *"quanti giorni ci mette a vendersi"* (schermata dedicata)

- ✅ **Pivot dei giorni di vendita** dai venduti (`venduto_rimosso`,
  found→sparizione): si sceglie di raggruppare per **modello / colore / taglia**
  in qualsiasi combinazione (uno, due, tutti o totale) e si filtra per valore
  (es. un modello → giorni per ogni suo colore). Tabella ordinata dal più veloce,
  con campione e prezzo mediano; righe sotto 3 venduti marcate come fragili.
  Dati già presenti, nuova dimensione colore/taglia prima inutilizzata.

### 7.3 Pipeline P&L — *"il gestionale che chiude il loop"*

- ✅ Stadi interessante → contattato → offerta → comprato → in_vendita →
  venduto / sfumato; costi accessori; profitto netto; riepilogo (investito,
  realizzato, margine reale medio)
- ✅ **Feedback loop visibile**: accuratezza stime, scarto medio (sotto/sovra-
  stima), stima→reale medio per i venduti
- ✅ **ROI/giorno realizzato** (margine reale ÷ giorni in stock)
- ✅ **Tempo-in-stadio + alert "fermo da troppo"**: giorni nello stadio corrente
  e nel ciclo, soglia per stadio (7gg interessante, 5gg contattato/offerta,
  14gg comprato, 30gg in vendita), livello attenzione/critico e — sui pezzi già
  comprati — **quanto ti è costato finora** in deprezzamento maturato. Badge in
  riga + banner di riepilogo.
- ✅ Dal 2026-10-05: esiti registrabili da Telegram (bottoni sotto l'alert,
  §1.6).

### 7.4 Automations / Salute — *"il motore gira bene?"*

- ✅ Job: avvio immediato, pausa/ripresa, cambio intervallo, prossima esecuzione
- ✅ **Pannello salute scraper** (da `scrape_runs`): stato per categoria,
  timeline ultimi giri, ultimo giro, stato proxy / impersonation
- ✅ **Copertura**: target attivi, annunci in magazzino, nuovi/24h per categoria
- ✅ Dal 2026-10-05: pannello **"Obiettivi della Goal Version"** (§5) sopra la
  Qualità del dato, con richieste per lavoro, emivita, deriva e consegna degli
  alert.

### 7.5 Impostazioni — *"configura senza toccare il codice"*

- ✅ **Impostazioni da UI**: soglie alert (score/margine/calo), margine obiettivo
  per categoria, **prezzi ricambi Apple** per fascia, chat Telegram. Salvate in
  `app_settings`, applicate a runtime (il token bot resta in `.env`).
- ✅ Dal 2026-10-05: tempi del €/ora, pulsanti di prova di Telegram, criteri
  degli alert auto.

> Scartati di proposito: **Home/Overview separata** (la fa Market Intelligence) e
> **storico notifiche** (già sul telefono via Telegram).

### Gap prioritari per "chiudere iPhone"

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
> **auto** (§8).

### Già solido (fondamenta, non toccare salvo rifiniture)

Scraper HTTP/JSON anti-Akamai (curl_cffi; il proxy è dismesso dal 2/10),
NLP (memoria/colore/batteria/difetti/corredo), varianti canoniche, valore
equo **dai venduti**, Deal Score, max bid, ROI/giorno, domanda-offerta,
confidence, pHash anti-ripubblicazione, shadow dealer, price history, Telegram
intelligente, copertura gamma iPhone (gamma completa fino alla gen 18, linea
Air inclusa; trattata dal 12 in su), Postgres self-hosted + Docker.

> ⚠️ **La gamma va tenuta al passo.** La flotta era ferma alla gen 16 mentre il
> 17 (17/Air/Pro/Pro Max/17e) era già sul mercato da mesi: modelli più cari,
> quindi più margine per pezzo, completamente ciechi. A ogni keynote: aggiungere
> la generazione in `scripts/seed_iphone_targets.py` **e** verificare che il
> resolver di variante conosca eventuali linee nuove (l'Air non c'era, e un
> "17 Air" finiva nel pool del 17 base a ~100€ di differenza).

## 8. Verticale auto — definizione di "fatto"

> Fissa **schermate, analitiche e funzionalità** che vogliamo per il verticale
> auto, gemello della §7. Quando (quasi) tutto qui è ✅, l'auto è "chiusa".

Stato: ✅ fatto · 🔧 parziale (c'è ma da rifinire / matura coi dati) · ◻️ da fare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

> **Principio.** Le 5 domande restano quelle dell'iPhone — *quanto vale davvero ·
> quanto posso pagarlo · quanto e quando lo rivendo · di chi mi fido · è sicuro
> comprarlo* — ma su un'auto **nessuna** si risponde con "modello + memoria".

### Ambito (decisione del 2026-10-05)

Il verticale auto serve a un amico che fa **flipping e compravendita**: la
versione avanzata copre **tutte le auto** di Subito (536.786 in vendita il
2026-10-05), non due modelli pilota. Raccolta sulla **stessa macchina** degli
iPhone, sviluppo **in parallelo** alla v1 iPhone.

Cosa lo rende possibile: Subito dà per ogni auto marca · modello **con la
generazione** · versione (es. *BMW · Serie 1 (E87) · 123d cat 5 porte Eletta
DPF*), kW, carrozzeria, porte, immatricolazione, classe emissioni. Niente
tabelle scritte a mano (quella BMW resta come ripiego).

Come si accende: `AUTO_FULL_CATEGORY=true` nel `.env` di root, poi
`docker compose up -d collector` (fino al 5/10 lo leggeva il servizio
`backend`, prima della divisione fra API e raccoglitore). Fa: sweep di tutta
la categoria per i nuovi (foto solo come URL), inventario a rotazione su
`AUTO_INVENTORY_SLICES` notti (default 4, ~1.350 richieste a notte), venduti a
fine ciclo senza verifica pagina per pagina (data = ultima volta vista,
±durata del ciclo), ripubblicazioni fuse, Garbage Collector auto spento. Il
feed filtra nel DB (max 5.000 righe valutate, ultimi 7 giorni senza filtro di
modello) con filtri a cascata Marca → Modello → Generazione.

Decisioni del 2026-10-05 sera:

- la raccolta di tutte le auto **resta accesa** sullo stesso IP; se arrivano
  blocchi, solo gli annunci nuovi (testa e sweep) senza inventario a
  rotazione (§4.1, §5);
- le **correzioni sulle auto sono in pausa** finché l'amico rivenditore non
  dice cosa non va o cosa vorrebbe; il lavoro tecnico che non richiede la sua
  esperienza continua;
- gli alert auto partono solo con almeno un criterio del compratore (marca,
  zona, raggio o budget) e con un margine oltre l'errore tipico del modello.

### 8.0 Perché l'auto non è "l'iPhone con altri nomi"

Da capire prima di scrivere codice: qui sta tutto il lavoro.

| | iPhone | Auto |
|---|---|---|
| Identità dell'oggetto | modello + memoria → **oggetto identico** | modello + **generazione + motore + allestimento + anno + km** |
| Prezzo in funzione di | variante (a gradini) | anno **e** km (**continuo**, due dimensioni) |
| Varianti per target | ~4 tagli memoria | decine di combinazioni |
| Difetti | schermo, batteria: costo noto | meccanica: costo **ignoto finché non guardi** |
| Costi di transazione | spedizione | **passaggio di proprietà, bollo, revisione, gommatura, tagliando** |
| Tempo di vendita | giorni | **settimane/mesi** |
| Rischio | non ricevi la merce / iCloud | **km scalati, incidenti non dichiarati, fermo amministrativo, finanziamento residuo** |
| Campione per variante | centinaia | **decine**, spesso meno di 10 |

Conseguenza pratica: le fondamenta tech (variante canonica → mediana → margine)
**non reggono così come sono**. Vanno riscritte per l'auto, non riusate.

### 8.1 Fondamenta da rifare — *"il bot deve capire cos'è l'auto che sta guardando"*

Senza questi, tutto il resto misura rumore. Sono la vera Fase 1 dell'auto.

- ✅ 🔴 **Variante canonica per generazione** (`variants._car_variant`, 2026-10-05):
  `modello@generazione` da `backend/data/car_generations.json` (la sigla scritta
  vince sull'anno; anno a cavallo o fuori tabella → `@nd`; altro modello o
  ricambio → `@escluso`). Retroattivo: `scripts/backfill_car_variants.py`.
  *Prima:* Oggi la
  variante è lo slug della query (`bmw-125i`) e la generazione entra solo se il
  target ha `min_year`/`max_year` nei `strict_filters` — che i nostri due target
  **non hanno**. Risultato misurato: un unico pool `bmw-125i` che copre
  **2008→2025 e 1.499€→30.900€**. Serve la generazione dedotta dall'anno
  (tabella per modello: E82/E88 2007-2013, F20/F21 2011-2019, F40 2019-…) e,
  quando dichiarata, la **motorizzazione**.
- 🔧 🔴 **Valore equo anno + km** (`valuation.fit_car_price_model`, 2026-10-05):
  log(prezzo) ~ età + km per generazione, anomali esclusi, niente
  estrapolazione, errore tipico dichiarato e un "affare" deve superarlo; senza
  modello affidabile → "non so". Km in migliaia ("184") corretti. Sui dati
  del PC: 125i F20/F21 −8,2%/anno, −1,8%/10.000 km, errore 12% (5 affari su
  29, prima 17 su 66 artefatti). 123d E8x: con la **carrozzeria** (coupé/cabrio
  +43%) e senza l'età (dentro 2007–2012 non incide a parità di km) errore 26%,
  −3,1%/10.000 km, 7 affari su 57. Corretti anche i falsi difetti ("frizione
  nuova", "pronta da vedere", graffi) che toglievano auto sane dal campione.
  *Prima:* Oggi la regressione è
  `prezzo ~ km` sul target intero e **ignora l'anno**: sui nostri dati stima un
  123d del 2007 con 280.000 km a **6.811€** (chiesto 4.500€ → "affare +52%") e
  un 125i 2013 con 60.000 km a **24.695€**. Su 66 annunci ne classifica
  **17 come "affare"**: sono artefatti, non occasioni. Serve regressione a due
  variabili (età, km) per generazione, con fallback esplicito quando il campione
  non basta — meglio "non so" che un numero inventato.
- ✅ 🔴 **Raggruppamento per modello** (`reads._model_key`, 2026-10-05): chiave
  = parte prima di `@`, etichetta dalla tabella ("BMW 125i"). *Prima:* Toglie l'ultimo
  segmento della variante (pensato per `iphone-15-pro-256`), quindi per le auto
  `bmw-123d` → **`bmw`**: nei facet del feed tutte le 66 auto finiscono sotto un
  unico modello "Bmw". Serve una chiave modello nativa dell'auto.
- ◻️ 🟡 **Campione minimo onesto**: con decine di annunci per variante, le soglie
  tech (3 attivi / 5 venduti) sono troppo permissive. Rivedere per l'auto e
  **mostrare sempre l'ampiezza del campione** accanto a ogni stima.
- 🔧 🟡 **NLP auto** (2026-10-05): riconosciuti distribuzione/catena fatta, tagliandi
  certificati, unico proprietario, revisione, gancio traino, GPL/metano; "frizione"
  è difetto solo se da fare. Mancano: km non congruenti dal testo, scadenza
  bombole. *Prima:* già ci sono km, anno, allestimenti e 7 difetti. Mancano i
  segnali che spostano davvero il prezzo: **cinghia/catena distribuzione fatta,
  tagliandi certificati, unico proprietario, revisione, gancio traino, GPL/metano
  (e scadenza bombole), km non congruenti, "vendo per inutilizzo"**.
- ◻️ 🟡 **Colonna `ai_analysis` assente** (resta da fare) su `live_opportunities_auto`: il prompt
  AI per le auto (`_PROMPT_AUTO`) è già scritto ma non ha dove scrivere, e
  `enrich_missing(category="automobile")` chiede colonne tech. Serve migrazione.

### 8.2 Feed / Live Sniper auto — *"cosa compro adesso"*

- ✅ Feed, card, espansa, triage (salva/scarta), viste e paginazione: **condivisi
  col tech**, funzionano già.
- ✅ **Il feed auto non va più in errore** (le query chiedevano colonne tech).
- ✅ 🔴 **Filtri nativi auto** (2026-10-05): modello+generazione, anno (da/a),
  km massimi, cambio, alimentazione, con conteggi dai facet. *Prima:* anno (da/a), km (fasce), cambio, alimentazione,
  generazione. Oggi la barra filtri è quella tech (memoria, colore, batteria):
  su un'auto è inutilizzabile.
- ✅ 🔴 **Card auto** (2026-10-05): anno · km · cambio · alimentazione; nella
  scheda il prezzo atteso con deprezzamento della generazione, o "valore equo
  non stimabile" spiegato. *Prima:* anno, km, cambio, alimentazione al posto di memoria/
  batteria/colore. Oggi km compare in coda a campi vuoti.
- ✅ 🟡 **Costo di acquisizione reale** (2026-10-05, `services/car_costs.py`): IPT da
  kW e maggiorazione provinciale (max 30%, D.M. 435/1998), emolumenti ACI,
  Motorizzazione, bolli; agenzia e preparazione dalle Impostazioni; scalati dal
  tetto d'acquisto e nel "margine netto" della scheda. kW dal campo di Subito,
  se mancano dal testo ("218cv") o dalla variante (segnati "stimati"). Senza
  valore equo niente tetto (prima: media di un pool misto). *Prima:* passaggio di proprietà (varia per kW e
  provincia), eventuale revisione e gommatura → il margine "vero" di un'auto non
  è prezzo − prezzo. Va nel max bid come i ricambi Apple sul tech.
- ✅ 🟡 **Checklist di visione** (2026-10-05, `services/car_checklist.py`): regole
  meccaniche generali dai dati dell'annuncio (PRA, km alla revisione,
  spessimetro, distribuzione, FAP/EGR, frizione, cambio automatico, bombole,
  capote, batteria, telaio). Niente difetti specifici del modello scritti a
  memoria: arriveranno con fonti o AI. *Prima:* per l'annuncio aperto: cosa chiedere/guardare
  prima di muoversi (tagliandi, distribuzione, ruggine sui punti noti del
  modello, prova a freddo). Il valore dell'auto lo decide il sopralluogo.
- ✅ ⚪ **Distanza dal venditore** (2026-10-05): coordinate del comune da Subito
  (migrazione 24), comune di casa nelle Impostazioni, "km da te", ordinamento
  "Più vicini", raggio negli alert. *Prima:*: su un'auto andare a vedere costa mezza giornata;
  ordinare per vicinanza ha senso più che sul tech.
- ✅ 🔴 **Alert sui criteri del compratore** (2026-10-05, `services/car_alerts.py`):
  margine netto dopo i costi ≥ soglia (default 800 €), budget, marche, zone;
  sempre valore equo affidabile, rischio non alto, auto sana; ribassi solo
  sulle auto salvate; messaggio con margine netto, costi, tetto ed errore
  della stima. Chat: `telegram_chat_auto` (Impostazioni). Dalla sera del 5/10
  serve almeno un criterio del compratore e un margine oltre l'errore tipico
  del modello (senza, erano ~2.500 "affari" al giorno).

### 8.3 Market Intelligence auto — *"cosa conviene / come si muove il mercato"*

- 🔧 Le analitiche per modello **ora rispondono** (fallivano in silenzio), ma
  restano tarate sul tech: "premio memoria" e "impatto condizione" non hanno
  senso qui.
- ✅ 🔴 **Curva prezzo/km e prezzo/anno per generazione** (2026-10-05): schermata
  Mercato auto (quanto pesano anno, km, kW, coupé, diesel, automatico per
  generazione) + calcolatore "Quanto vale?". *Prima:*: l'equivalente auto
  della curva di deprezzamento iPhone, e la base del valore equo.
- ✅ 🔴 **Dove cacciare** (2026-10-05, `services/car_hunt.py`, schermata omonima): per
  modello@generazione attive, nuove/sparite a settimana, prezzo tipico, errore
  del modello, affari (margine netto dopo i costi sopra 500 € e sopra l'errore),
  margine tipico, potenziale €/settimana; clic → feed filtrato per margine.
- ◻️ 🟡 **Confronto tra generazioni** dello stesso modello (E82 vs F20 vs F40):
  dove si compra meglio oggi.
- ◻️ 🟡 **Prezzo per fascia di km** (0-50k, 50-100k, …): come si muove il mercato
  a parità di generazione.
- ◻️ ⚪ **Stagionalità**: cabrio d'estate, 4x4 d'inverno, e il crollo di agosto.
  Aspetta storico.

### 8.4 Tempo di vendita e liquidità — *"quanto resta ferma"*

- 🔧 Il Garbage Collector traccia già i rimossi anche per le auto → il pivot dei
  giorni di vendita funzionerà, ma con **dimensioni sbagliate** (colore/taglia
  invece di generazione/km/alimentazione).
- ✅ 🟡 **Costo di magazzino auto** (2026-10-05, `car_costs.carry_costs`): deprezzamento
  dal modello di prezzo (% annua della generazione) per i giorni di vendita
  (dai venduti del modello, altrimenti Impostazioni: 45), più assicurazione,
  posto e bollo pro rata; nel tetto e nel margine netto. *Prima:* un'auto ferma costa **assicurazione, bollo,
  posto auto e deprezzamento** — molto più di un iPhone. Va quantificato, come
  fatto sul tech.

### 8.5 Fiducia e sicurezza — *"di chi mi fido, è sicuro comprarla"*

Il Risk Score attuale è **solo tech** (iCloud, per-ricambi). Per l'auto serve
tutto un altro set:

- ✅ 🔴 **Km non congruenti** (2026-10-05, `scoring.car_risk_assessment`): sotto
  5.000 km/anno su un'auto di 4+ anni → segnale. *Prima:* km troppo bassi per l'anno (o rispetto alla media
  della generazione) → sospetto **scalamento contachilometri**. Dato già in
  mano: anno + km + distribuzione della variante.
- 🔧 🔴 **Incidenti non dichiarati** (2026-10-05): linguaggio evasivo ("motore da
  vedere", "così com'è", "per commercianti"), incidentata dichiarata, prezzo
  sospetto, nessuna foto; regole tarate sui dati veri ("radiatore nuovo" e
  "pronta da vedere" non scattano). Manca: foto solo da un lato. *Prima:* linguaggio evasivo ("da vedere", "piccolo
  urto"), foto solo da un lato, prezzo fuori scala verso il basso.
- ✅ 🟡 **Fermo amministrativo / finanziamento residuo / provenienza estera**
  (2026-10-05): rischio alto da solo; con qualunque segnale la scheda ricorda
  visura PRA e prova a freddo. *Prima:*
  segnali testuali, e la raccomandazione di verificare la visura PRA prima di
  muovere soldi.
- ✅ 🟡 **Concessionario travestito da privato** (2026-10-05): soglia auto a più
  di 1 auto tracciata in vendita (iPhone: più di 3). *Prima:* lo Shadow Dealer c'è già ma sui
  numeri auto va ritarato (un privato con 3 auto attive è sospetto; su iPhone no).

### 8.6 Pipeline P&L auto

- ✅ Funziona già (stadi, costi accessori, profitto netto, affari fermi).
- ✅ 🟡 **Costi accessori preimpostati per l'auto** (2026-10-05): editor costi in
  pipeline con voci per verticale, passaggio precompilato dalla stima. *Prima:*: passaggio, meccanico,
  gommatura, tagliando, lavaggio/dettaglio — oggi vanno scritti a mano ogni volta.

### 8.7 Copertura e raccolta

- ✅ Sniper auto ogni 15', 2 target (BMW 123d, 125i), 66 annunci attivi.
- ✅ 🔴 **Flotta auto vera** (2026-10-05): tutte le auto, codice pronto dietro
  `AUTO_FULL_CATEGORY` (vedi *Ambito*). Provato dal vivo su 2 pagine: 199 auto
  di 33 marche con dati strutturati. *Prima:* due target sono un pilota. Definire il perimetro —
  quali modelli, quali fasce di prezzo, quale raggio geografico — è una
  **decisione di business**, non tecnica, e va presa prima di allargare.
- ◻️ 🟡 **Target per generazione** invece che per modello: un target
  `BMW 123d 2007-2013` con `strict_filters` popolati risolve metà dei problemi
  di variante senza toccare il codice.

### Gap prioritari per "chiudere auto"

1. 🔴 **Variante per generazione** + **chiave modello nativa** (§8.1)
2. 🔴 **Valore equo anno+km** con onestà sul campione (§8.1)
3. 🔴 **Feed nativo auto**: filtri e card con anno/km/cambio/alimentazione (§8.2)
4. 🔴 **Risk Score auto**: km scalati, incidenti, fermo amministrativo (§8.5)
5. 🟡 **Costi reali** (passaggio & co.) dentro il max bid e nella pipeline (§8.2, §8.6)
6. 🟡 **Curve prezzo/km e prezzo/anno** per generazione (§8.3)
7. 🟡 **Perimetro della flotta** — decisione da prendere (§8.7)

> **Ordine consigliato:** 1 → 2 → 3, in quest'ordine e senza saltare. Finché la
> variante mescola 17 anni di modelli, ogni numero a valle è rumore: oggi il bot
> dichiara "affare" 17 annunci su 66, e **nessuno di quei margini è reale**.
> *(Stato al 2026-10-05: i punti 1–6 sono fatti o parziali, vedi le voci
> sopra; il perimetro è deciso, tutte le auto, vedi Ambito.)*

### Già solido (ereditato dal tech, funziona anche qui)

Scraper HTTP/JSON anti-Akamai con filtri nativi auto (anno/km/cambio),
paginazione, anti-spam, pHash anti-ripubblicazione, dedup, price history e watch
di prezzo, Shadow Dealer, triage e viste, pipeline P&L, alert Telegram su chat
dedicata, salute scraper, Garbage Collector, merge multi-istanza.

## 9. Backlog aperto e idee

### Piano BI per fasi (stato al 2026-10-02)

| Fase | Contenuto | Stato |
|---|---|---|
| **Fase 1** | Tassonomia canonica & scrematura (varianti, condizione) | ✅ |
| **Fase 2** | Valutazione predittiva (valore equo, posizione, affare-vs-truffa) | ✅ |
| **Fase 3 — robustezza** | Salute scraper, alert down, rotazione impersonation | ✅ |
| **Fase 3 — scala** | Generazione sistematica dei target: gamma iPhone completa ✅ (`scripts/seed_iphone_targets.py`, 39 modelli fino alla gen 18) + ricerca ampia che copre anche i modelli senza target ✅, gamma auto 🔜 (dal 5/10 tutte le auto, §8) | 🟡 |
| **Fase 4** | Profili venditore, stagionalità, CV foto, multi-piattaforma | 🔜 |
| **Fase 5** | Ops: automations reali ✅, deploy VPS 🔜, test, migration runner | 🟡 (in corso) |

### In discussione

#### 💬 Valutazione condition-aware delle condizioni (ML/AI) — punto 1, da definire insieme

La schermata Tempo di vendita deve mostrare (quasi) tutti i venduti in un
grafico prezzo↔giorni, ma condizione/difetti/corredo cambiano il prezzo più di
ogni altra cosa e oggi non sono isolati nel grafico. Due strade proposte:

1. **Filtro semplice**: grafico limitato ai venduti "come nuovo"/sani (già
   distinguibile con `condition_tier`), pulito ma butta via molti dati.
2. **Modello di pricing per feature** (no deep ML: regressione tipo quella già
   usata per il prezzo~km delle auto) che stima l'impatto di condizione,
   batteria, difetti, corredo sul prezzo, usando i dati NLP/AI già estratti.

Il punto 9 dello [storico](STORICO.md) (fix della sovrastima del valore equo)
è un primo passo in questa direzione (segmentazione per fascia condizione sui
venduti) fatto con metodo "semplice", senza ML.

### Idee per dopo la v1 (non bloccanti)

- **Visione sulle foto** con un modello multimodale locale: schermo crepato,
  scocca, condizione e danni; foto di catalogo (truffa); verifica che
  l'oggetto corrisponda al titolo.
- **Altre piattaforme** (Vinted, Facebook Marketplace, AutoScout24) per
  comprare e rivendere, anche in arbitraggio fra piattaforme (compro su A,
  rivendo su B).
- **Stagionalità** (finestra keynote per gli iPhone; per le auto §8.3), quando
  ci sono mesi di storico.
- **Frontend in tempo reale** (SSE/WebSocket) invece del polling.
- Il **verticale auto**, che era qui fra le idee, è diventato la §8.
