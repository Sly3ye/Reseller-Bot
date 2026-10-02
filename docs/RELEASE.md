# Versione release (v1.0) — definizione e distanza

> Bozza del 2026-10-02. Serve da **punto di riferimento**: cosa deve fare il
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
| A2 | Copertura ≥ 95% degli iPhone che Subito dichiara (misurata dall'inventario notturno) | 🔧 primo inventario stanotte |
| A3 | Zero annunci persi tra un giro e l'altro (`gaps` = 0 per 14 giorni di fila) | 🔧 da osservare |
| A4 | Venduti/rimossi rilevati ogni notte (inventario + verifica) | ✅ codice · 🔧 primi dati stanotte |
| A5 | Gira da solo 30 giorni senza interventi, su UNA macchina sempre accesa | ◻️ oggi PC + Mac separati |

### B. Qualità del dato — sapere cosa c'è nell'annuncio

| # | Criterio | Stato |
|---|---|---|
| B1 | Modello riconosciuto ≥ 97% degli annunci attivi | 🔧 96,5% |
| B2 | Memoria ≥ 85% | 🔧 74,5% |
| B3 | **Guasto classificato per tipo** (tassonomia in `services/defects.py`) con F1 ≥ 0,90 sulla serie di **verifica** etichettata (`scripts/eval_guasti.py`) | 🔧 regex v2: precisione 0,91 ma richiamo 0,48 (F1 0,62) su annunci mai visti — serve l'AI per il richiamo |
| B4 | **Parti non originali** riconosciute (display/batteria già sostituiti: pesano sul prezzo) | 🔧 regex: F1 0,77 in verifica |
| B5 | Modello AI locale scelto **su misure**, che copre tutti gli annunci rilevanti | 🔧 prompt v2 e banco di prova pronti; misura dei candidati da fare sul Mac |

### C. Metriche per il business

| # | Criterio | Stato |
|---|---|---|
| C1 | Costi ricambi per modello in due colonne (Apple con credito di reso, aftermarket) | ✅ |
| C2 | **Sconto rotto vs sano per modello × guasto** (non un unico "rotto") | ◻️ |
| C3 | **Prezzo di rivendita del riparato** (con parti non originali), misurato sul mercato | ◻️ |
| C4 | Tempo di vendita onesto (Kaplan–Meier), venduto/ritirato/scaduto separati | ✅ codice · 🔧 servono 4–6 settimane di venduti |
| C5 | **Matrice opportunità modello × guasto**: prezzo tipico d'acquisto, riparazione, rivendita, margine, giorni, annunci/settimana | ◻️ |
| C6 | Concorrenza sui rotti: quanto in fretta spariscono quelli sottoprezzati | ◻️ matura coi dati |

### D. Decisione sul singolo annuncio

| # | Criterio | Stato |
|---|---|---|
| D1 | Tetto d'acquisto per i rotti = rivendita del riparato − ricambio − manodopera − magazzino − margine | 🔧 c'è, ma con rivendita da "sano originale" (C3) |
| D2 | Rischio (iCloud, truffa, venditore) | ✅ |
| D3 | **Alert Telegram per le opportunità di riparazione** (oggi gli alert seguono il margine da "sano") | ◻️ |
| D4 | Sani sottoprezzati segnalati comunque | ✅ |

### E. Imparare dalle proprie riparazioni

| # | Criterio | Stato |
|---|---|---|
| E1 | Pipeline P&L con stima vs reale | ✅ |
| E2 | Per ogni riparazione: pezzo usato, costo reale, tempo, esito (riuscita/fallita), prezzo di vendita | ◻️ |
| E3 | I dati reali correggono costi (C1), rivendita (C3) e il tasso di fallimento dei "non si accende" | ◻️ |

### F. Operatività

| # | Criterio | Stato |
|---|---|---|
| F1 | Migrazioni automatiche all'avvio | ✅ |
| F2 | Backup automatico del DB (e delle foto) con verifica di ripristino | 🔧 script presenti, non schedulati |
| F3 | Allarmi di sistema (blocco, giro down) | ✅ |
| F4 | Cruscotto qualità del dato | ✅ |

## Distanza

- **Fatto:** la base (A1, A4, C1, C4, D2, D4, E1, F1, F3, F4).
- **Sviluppo che manca, in ordine:** B3+B4 → B5 → C2 → C3 → C5 → D1/D3 → E2/E3
  → A5/F2. Il cuore è B3: tutte le metriche di riparazione stanno sopra la
  classificazione dei guasti.
- **Tempo che nessuno sviluppo accorcia:** venduti e tempi di vendita (C4, C6)
  diventano affidabili solo con **4–6 settimane** di inventari notturni.
  Conviene quindi spostare presto la raccolta su una macchina sempre accesa (A5).

Stima onesta: con B3–C5 fatti, il programma è **usabile per decidere** anche
prima che C4 maturi; è **v1** quando anche C4/C6 hanno dati e A5 è risolto.

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
