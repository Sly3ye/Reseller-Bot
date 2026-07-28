# Visione & Definizione di "fatto" — verticale auto

Documento vivo, gemello di [VISIONE-IPHONE.md](VISIONE-IPHONE.md): fissa
**schermate, analitiche e funzionalità** che vogliamo per il verticale auto.
Quando (quasi) tutto qui è ✅, l'auto è "chiusa".

Stato: ✅ fatto · 🔧 parziale (c'è ma da rifinire / matura coi dati) · ◻️ da fare
Priorità: 🔴 alta · 🟡 media · ⚪ bassa

> **Principio.** Le 5 domande restano quelle dell'iPhone — *quanto vale davvero ·
> quanto posso pagarlo · quanto e quando lo rivendo · di chi mi fido · è sicuro
> comprarlo* — ma su un'auto **nessuna** si risponde con "modello + memoria".

---

## 0. Perché l'auto non è "l'iPhone con altri nomi"

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

---

## 1. Fondamenta da rifare — *"il bot deve capire cos'è l'auto che sta guardando"*

Senza questi, tutto il resto misura rumore. Sono la vera Fase 1 dell'auto.

- ◻️ 🔴 **Variante canonica per generazione** (`variants._car_variant`). Oggi la
  variante è lo slug della query (`bmw-125i`) e la generazione entra solo se il
  target ha `min_year`/`max_year` nei `strict_filters` — che i nostri due target
  **non hanno**. Risultato misurato: un unico pool `bmw-125i` che copre
  **2008→2025 e 1.499€→30.900€**. Serve la generazione dedotta dall'anno
  (tabella per modello: E82/E88 2007-2013, F20/F21 2011-2019, F40 2019-…) e,
  quando dichiarata, la **motorizzazione**.
- ◻️ 🔴 **Valore equo anno + km** (`valuation`). Oggi la regressione è
  `prezzo ~ km` sul target intero e **ignora l'anno**: sui nostri dati stima un
  123d del 2007 con 280.000 km a **6.811€** (chiesto 4.500€ → "affare +52%") e
  un 125i 2013 con 60.000 km a **24.695€**. Su 66 annunci ne classifica
  **17 come "affare"**: sono artefatti, non occasioni. Serve regressione a due
  variabili (età, km) per generazione, con fallback esplicito quando il campione
  non basta — meglio "non so" che un numero inventato.
- ◻️ 🔴 **Raggruppamento per modello** (`reads._model_key`). Toglie l'ultimo
  segmento della variante (pensato per `iphone-15-pro-256`), quindi per le auto
  `bmw-123d` → **`bmw`**: nei facet del feed tutte le 66 auto finiscono sotto un
  unico modello "Bmw". Serve una chiave modello nativa dell'auto.
- ◻️ 🟡 **Campione minimo onesto**: con decine di annunci per variante, le soglie
  tech (3 attivi / 5 venduti) sono troppo permissive. Rivedere per l'auto e
  **mostrare sempre l'ampiezza del campione** accanto a ogni stima.
- ◻️ 🟡 **NLP auto**: già ci sono km, anno, allestimenti e 7 difetti. Mancano i
  segnali che spostano davvero il prezzo: **cinghia/catena distribuzione fatta,
  tagliandi certificati, unico proprietario, revisione, gancio traino, GPL/metano
  (e scadenza bombole), km non congruenti, "vendo per inutilizzo"**.
- ◻️ 🟡 **Colonna `ai_analysis` assente** su `live_opportunities_auto`: il prompt
  AI per le auto (`_PROMPT_AUTO`) è già scritto ma non ha dove scrivere, e
  `enrich_missing(category="automobile")` chiede colonne tech. Serve migrazione.

## 2. Feed / Live Sniper auto — *"cosa compro adesso"*

- ✅ Feed, card, espansa, triage (salva/scarta), viste e paginazione: **condivisi
  col tech**, funzionano già.
- ✅ **Il feed auto non va più in errore** (le query chiedevano colonne tech).
- ◻️ 🔴 **Filtri nativi auto**: anno (da/a), km (fasce), cambio, alimentazione,
  generazione. Oggi la barra filtri è quella tech (memoria, colore, batteria):
  su un'auto è inutilizzabile.
- ◻️ 🔴 **Card auto**: anno, km, cambio, alimentazione al posto di memoria/
  batteria/colore. Oggi km compare in coda a campi vuoti.
- ◻️ 🟡 **Costo di acquisizione reale**: passaggio di proprietà (varia per kW e
  provincia), eventuale revisione e gommatura → il margine "vero" di un'auto non
  è prezzo − prezzo. Va nel max bid come i ricambi Apple sul tech.
- ◻️ 🟡 **Checklist di visione** per l'annuncio aperto: cosa chiedere/guardare
  prima di muoversi (tagliandi, distribuzione, ruggine sui punti noti del
  modello, prova a freddo). Il valore dell'auto lo decide il sopralluogo.
- ⚪ **Distanza dal venditore**: su un'auto andare a vedere costa mezza giornata;
  ordinare per vicinanza ha senso più che sul tech.

## 3. Market Intelligence auto — *"cosa conviene / come si muove il mercato"*

- 🔧 Le analitiche per modello **ora rispondono** (fallivano in silenzio), ma
  restano tarate sul tech: "premio memoria" e "impatto condizione" non hanno
  senso qui.
- ◻️ 🔴 **Curva prezzo/km e prezzo/anno per generazione**: l'equivalente auto
  della curva di deprezzamento iPhone, e la base del valore equo.
- ◻️ 🟡 **Confronto tra generazioni** dello stesso modello (E82 vs F20 vs F40):
  dove si compra meglio oggi.
- ◻️ 🟡 **Prezzo per fascia di km** (0-50k, 50-100k, …): come si muove il mercato
  a parità di generazione.
- ◻️ ⚪ **Stagionalità**: cabrio d'estate, 4x4 d'inverno, e il crollo di agosto.
  Aspetta storico.

## 4. Tempo di vendita e liquidità — *"quanto resta ferma"*

- 🔧 Il Garbage Collector traccia già i rimossi anche per le auto → il pivot dei
  giorni di vendita funzionerà, ma con **dimensioni sbagliate** (colore/taglia
  invece di generazione/km/alimentazione).
- ◻️ 🟡 **Costo di magazzino auto**: un'auto ferma costa **assicurazione, bollo,
  posto auto e deprezzamento** — molto più di un iPhone. Va quantificato, come
  fatto sul tech.

## 5. Fiducia e sicurezza — *"di chi mi fido, è sicuro comprarla"*

Il Risk Score attuale è **solo tech** (iCloud, per-ricambi). Per l'auto serve
tutto un altro set:

- ◻️ 🔴 **Km non congruenti**: km troppo bassi per l'anno (o rispetto alla media
  della generazione) → sospetto **scalamento contachilometri**. Dato già in
  mano: anno + km + distribuzione della variante.
- ◻️ 🔴 **Incidenti non dichiarati**: linguaggio evasivo ("da vedere", "piccolo
  urto"), foto solo da un lato, prezzo fuori scala verso il basso.
- ◻️ 🟡 **Fermo amministrativo / finanziamento residuo / provenienza estera**:
  segnali testuali, e la raccomandazione di verificare la visura PRA prima di
  muovere soldi.
- ◻️ 🟡 **Concessionario travestito da privato**: lo Shadow Dealer c'è già ma sui
  numeri auto va ritarato (un privato con 3 auto attive è sospetto; su iPhone no).

## 6. Pipeline P&L auto

- ✅ Funziona già (stadi, costi accessori, profitto netto, affari fermi).
- ◻️ 🟡 **Costi accessori preimpostati per l'auto**: passaggio, meccanico,
  gommatura, tagliando, lavaggio/dettaglio — oggi vanno scritti a mano ogni volta.

## 7. Copertura e raccolta

- ✅ Sniper auto ogni 15', 2 target (BMW 123d, 125i), 66 annunci attivi.
- ◻️ 🔴 **Flotta auto vera**: due target sono un pilota. Definire il perimetro —
  quali modelli, quali fasce di prezzo, quale raggio geografico — è una
  **decisione di business**, non tecnica, e va presa prima di allargare.
- ◻️ 🟡 **Target per generazione** invece che per modello: un target
  `BMW 123d 2007-2013` con `strict_filters` popolati risolve metà dei problemi
  di variante senza toccare il codice.

---

## Gap prioritari per "chiudere auto"

1. 🔴 **Variante per generazione** + **chiave modello nativa** (§1)
2. 🔴 **Valore equo anno+km** con onestà sul campione (§1)
3. 🔴 **Feed nativo auto**: filtri e card con anno/km/cambio/alimentazione (§2)
4. 🔴 **Risk Score auto**: km scalati, incidenti, fermo amministrativo (§5)
5. 🟡 **Costi reali** (passaggio & co.) dentro il max bid e nella pipeline (§2, §6)
6. 🟡 **Curve prezzo/km e prezzo/anno** per generazione (§3)
7. 🟡 **Perimetro della flotta** — decisione da prendere (§7)

> **Ordine consigliato:** 1 → 2 → 3, in quest'ordine e senza saltare. Finché la
> variante mescola 17 anni di modelli, ogni numero a valle è rumore: oggi il bot
> dichiara "affare" 17 annunci su 66, e **nessuno di quei margini è reale**.

---

## Già solido (ereditato dal tech, funziona anche qui)

Scraper HTTP/JSON anti-Akamai con filtri nativi auto (anno/km/cambio),
paginazione, anti-spam, pHash anti-ripubblicazione, dedup, price history e watch
di prezzo, Shadow Dealer, triage e viste, pipeline P&L, alert Telegram su chat
dedicata, salute scraper, Garbage Collector, merge multi-istanza.

_Aggiungere qui le nuove idee man mano che emergono._
