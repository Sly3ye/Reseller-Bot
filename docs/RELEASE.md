# Versione release (v1.0) — definizione e distanza

> Bozza del 2026-10-02, rivalutata lo stesso giorno dopo un audit completo
> della gestione dati (sezione G). Serve da **punto di riferimento**: cosa deve fare il
> programma per essere "pronto" per il business, e quanto manca. Si rivaluta
> spesso (a ogni giro di sviluppo) e può crescere: le idee nuove vanno in
> fondo, nella sezione *Dopo la v1*, a meno che non blocchino il business.

## Il business che la v1 deve servire

Comprare **iPhone rotti o difettosi** su Subito, ripararli (con ricambi
aftermarket o originali) e rivenderli. In secondo piano: segnalare i **sani
sottoprezzati**, rari ma da non perdere.

Per ogni annuncio la v1 deve rispondere con numeri affidabili a:

1. **Che guasto ha, e si ripara?** (tipo di guasto, riparabile / a rischio / invendibile)
2. **Quanto costa ripararlo?** (ricambio aftermarket o Apple + manodopera)
3. **A quanto lo rivendo riparato, e in quanto tempo?**
4. **Quanto posso pagarlo al massimo?** (tetto d'acquisto, già al netto di tutto)
5. **È sicuro comprarlo?** (truffa, iCloud, venditore)

E per il mercato: **dove conviene cacciare** (quali modelli × guasti rendono
di più e girano in fretta).

## Criteri di "pronto"

Stato: ✅ fatto · 🔧 c'è ma non basta / va misurato · ◻️ manca

### A. Raccolta — vedere tutto il mercato, gratis

| # | Criterio | Stato |
|---|---|---|
| A1 | Nessun servizio a pagamento; ritmo sotto la soglia di blocco, stop automatico sui 403 | ✅ |
| A2 | Copertura ≥ 95% della ricerca che Subito dichiara (annunci letti / dichiarati, dall'inventario) | ✅ 99,95% (51.643 letti su 51.669, inventario del 2026-10-02, completo) · da mantenere ogni notte |
| A3 | Zero annunci persi tra un giro e l'altro (`gaps` = 0 per 14 giorni di fila) | 🔧 da osservare |
| A4 | Venduti/rimossi rilevati ogni notte (inventario + verifica) | ✅ codice: esito sempre registrato, allarme se interrotto/incompleto, recupero automatico se il PC era spento all'1:30 · 🔧 primi dati con l'inventario di oggi |
| A5 | Gira da solo 30 giorni senza interventi, su UNA macchina sempre accesa | ◻️ oggi PC + Mac separati |

### B. Qualità del dato — sapere cosa c'è nell'annuncio

| # | Criterio | Stato |
|---|---|---|
| B1 | Modello riconosciuto ≥ 97% degli annunci attivi | ✅ 97,8% (anche dalla descrizione se il titolo dice solo "iPhone") |
| B2 | Memoria letta in ≥ 95% degli annunci che la scrivono (prima: "≥ 85% di tutti") | ✅ ~97% di chi la scrive · 80,1% di tutti: il ~18% degli annunci non riporta alcun taglio, nessuna regola o AI lo può leggere dal testo |
| B3 | **Guasto classificato per tipo** (tassonomia in `services/defects.py`) con F1 ≥ 0,90 sulla serie di **verifica** etichettata (`scripts/eval_guasti.py`) | 🔧 regex v2: precisione 0,91 ma richiamo 0,48 (F1 0,62) su annunci mai visti — serve l'AI per il richiamo |
| B4 | **Parti non originali** riconosciute (display/batteria già sostituiti: pesano sul prezzo) | 🔧 regex: F1 0,77 in verifica |
| B5 | Modello AI locale scelto **su misure**, che copre tutti gli annunci rilevanti | 🔧 prompt v2 e banco di prova pronti; misura dei candidati da fare sul Mac |

### C. Metriche per il business

| # | Criterio | Stato |
|---|---|---|
| C1 | Costi ricambi per modello in due colonne (Apple con credito di reso, aftermarket) | ✅ |
| C2 | **Sconto rotto vs sano per modello × guasto** (non un unico "rotto") | ✅ matrice Riparazioni |
| C3 | **Prezzo di rivendita del riparato** (con parti non originali), misurato sul mercato | ✅ schermo non originale −15,6%, batteria −2% (misurati) |
| C4 | Tempo di vendita onesto (Kaplan–Meier), venduto/ritirato/scaduto separati | ✅ codice · 🔧 servono 4–6 settimane di venduti |
| C5 | **Matrice opportunità modello × guasto**: prezzo tipico d'acquisto, riparazione, rivendita, margine, giorni, annunci/settimana | ✅ schermata Riparazioni (giorni di vendita: con i venduti) |
| C6 | Concorrenza sui rotti: quanto in fretta spariscono quelli sottoprezzati | ◻️ matura coi dati |

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
| F6 | Foto di tutti gli annunci (anche archivio) | ✅ backfill dalla CDN immagini, a lotti, sicuro sui blocchi · 🔧 ~45k annunci in coda, ~13 h |

### G. Affidabilità del dato (audit 2026-10-02)

Senza questi, le metriche C4/C5 e gli alert possono essere *precisi ma
sbagliati*. Corretti oggi:

| # | Problema trovato | Stato |
|---|---|---|
| G1 | Ripubblicazioni: un negozio che vende un pezzo e ne carica uno uguale "cancellava" la vendita; il pHash fondeva annunci di venditori diversi con la stessa foto di catalogo | ✅ serve lo stesso venditore; chi ha 2 pezzi uguali online insieme è un negozio e non si abbina |
| G2 | Kaplan–Meier senza entrata ritardata: lo stock trovato già vecchio (backfill) avrebbe allungato i tempi di vendita per mesi | ✅ troncamento a sinistra (entrata = età quando l'abbiamo visto) |
| G3 | "Scaduto dopo un anno": falso, 1.528 iPhone di privati online da 12–21 mesi | ✅ soglia a 2 anni; sotto decidono le regole sul ritirato |
| G4 | Inventario: pagina vuota a metà fascia = "completo"; errori diversi dal blocco senza traccia; job notturni in UTC (2h dopo il previsto); Motore Notturno a orario fisso anche con inventario in corso | ✅ completezza per annunci letti, esito e allarme sempre, fuso Europe/Rome, Motore Notturno a valle dell'inventario |
| G5 | Annunci in moderazione dietro il segnalibro dello sweep (margine 10 min) | ✅ margine 2 h · 🔧 da misurare: nuovi recenti trovati solo dall'inventario |
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
| G13 | **Latenza annuncio → alert** misurata (p50/p95): nel business dei rotti vince chi arriva primo | ✅ misura nel cruscotto (scoperta, tardivi oltre 2h, alert) · 🔧 significativa dopo un giorno di raccolta continua; alert solo con Telegram configurato |
| G14 | **Prezzo di realizzo ≠ prezzo chiesto**: fattore di trattativa dalle proprie compravendite, applicato a rivendita e tetto | ◻️ si attiva con la pipeline (come E3) |
| G15 | **Incertezza visibile**: campione accanto a ogni cifra di matrice, tetto e alert; matrice per memoria (il mix 64/128/256 differisce tra rotti e sani) | ✅ campione e celle fragili nella matrice, confidenza sul valore equo; margini della matrice col sano a parità di memoria (scheda e tetto lo erano già: valore equo per variante modello+memoria) |
| G16 | Unione dei DB PC+Mac senza false vendite (le sparizioni durante il fermo di una macchina) | ✅ merge del 2026-10-03 sul Mac (51.794 annunci tech); foto ancora da importare · dopo A5 non servirà più |

## Distanza

- **Fatto:** la base (A1, A4, B1, B2, C1, C2, C3, C5, D1–D4, E1, E2, F1–F4, F6) e
  l'affidabilità del dato G1–G10.
- **Sviluppo che manca, in ordine:**
  1. **A5 — una macchina sempre accesa.** È il collo di bottiglia: senza
     inventari ogni notte C4/C6/G11 non maturano mai. Deciso questo, i dati
     del PC si uniscono una volta e poi c'è un solo DB.
  2. **G11 + G12** — validare venduto e ripubblicazioni su campioni a mano
     (mezza giornata di etichettatura, dopo una settimana di inventari).
  3. **B5 → B3/B4** — modello AI misurato sul Mac, poi guasti oltre le regex.
  4. **G13, G15** — latenza degli alert e incertezza visibile.
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

## Come si misura il riconoscimento dei guasti

Due serie etichettate a mano in `scripts/data/`:
- **sviluppo** (145 annunci): usata per scrivere le regex → i suoi numeri sono
  ottimisti per costruzione (F1 0,98);
- **verifica** (99 annunci, campionati per fascia di prezzo): **mai** usata per
  correggere le regole → è il numero onesto. Se le si usa per correggere,
  perde valore: in quel caso si etichetta una serie nuova.

`python scripts/eval_guasti.py --set verifica [--models a,b,c]` misura regex e
modelli AI con le stesse metriche. Dopo ogni miglioramento del riconoscimento:
`scripts/reparse_nlp.py --apply` lo rende retroattivo sull'archivio.

## Dopo la v1 (idee, non bloccanti)

- Visione sulle foto (schermo crepato, scocca) con un modello multimodale locale.
- Verticale auto ([VISIONE-AUTO.md](VISIONE-AUTO.md)).
- Altre piattaforme (Vinted, Facebook Marketplace) per comprare / rivendere.
- Stagionalità (finestra keynote), quando ci sono mesi di storico.
