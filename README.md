# FlipRadar — Reseller Arbitrage Bot

Sistema automatico di **arbitraggio su annunci di seconda mano** (smartphone e automobili) che monitora Subito.it 24/7, calcola il prezzo medio di mercato per ogni modello tracciato, segnala in tempo reale (anche su Telegram) gli annunci sottoprezzati con margine di rivendita stimato e ne accompagna l'intero ciclo compra-rivendi in una pipeline P&L.

Nato come strumento operativo per **due attività reali**: rivendita di iPhone usati (verticale *tech*) e di auto usate (verticale *auto*), con statistiche e margini isolati per verticale.

Il progetto è diviso in tre parti:

| Componente | Ruolo | Stack |
|---|---|---|
| **Backend** (`backend/`) | Motori di scraping, NLP, scoring, notifiche, API REST | Python 3.11+, FastAPI, APScheduler, httpx |
| **Frontend** (`frontend/`) | Dashboard operativa (Live Sniper, Market Intelligence, Pipeline P&L, Automations) | Next.js 16, React 19, TypeScript |
| **Database** (`database/`) | Schema consolidato + immagini su filesystem | **PostgreSQL self-hosted** (psycopg), storage locale |

> **Self-hosted, zero abbonamenti.** Il progetto girava su Supabase; è stato migrato a **PostgreSQL self-hosted + storage immagini su disco**, così gira sul tuo hardware (mini PC o VPS ~€5/mese) senza limiti né canoni. L'accesso ai dati passa da un layer compatibile (`backend/core/database.py`) che mantiene la stessa API del vecchio client, quindi tutta la logica di business è invariata. Tutto parte con `docker compose up`.

---

## Indice

- [Architettura](#architettura)
- [Struttura del codice](#struttura-del-codice)
- [Modello dati](#modello-dati)
- [Feature principali](#feature-principali)
- [Data Intelligence: dal dato alla decisione d'acquisto](#data-intelligence-dal-dato-alla-decisione-dacquisto)
- [Come funziona: il flusso end-to-end](#come-funziona-il-flusso-end-to-end)
- [Tecnologie utilizzate](#tecnologie-utilizzate)
- [Setup e comandi](#setup-e-comandi)
- [Configurazione (.env)](#configurazione-env)
- [API REST](#api-rest)
- [Script operativi](#script-operativi)
- [Note di design / limiti noti](#note-di-design--limiti-noti)

---

## Architettura

```
                         ┌─────────────────────────┐
                         │   hades.subito.it        │
                         │  (API JSON interna SPA)  │
                         └────────────┬─────────────┘
                                      │ HTTP/JSON (proxy residenziale)
                                      ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                        BACKEND (FastAPI)                       │
   │                                                                 │
   │  ┌───────────────┐   ┌───────────────────┐   ┌──────────────┐  │
   │  │  SubitoScraper │──▶│   NLP Parser       │──▶│  tasks.py    │  │
   │  │ (split routing)│   │ (regex, 0 dipend.) │   │ (motori +    │  │
   │  └───────────────┘   └───────────────────┘   │  business     │  │
   │         │                                     │  logic)       │  │
   │         │ immagini (CDN diretta)               └──────┬───────┘  │
   │         ▼                                             │          │
   │  ┌───────────────┐                                    ▼          │
   │  │ pHash + salva  │                          ┌──────────────────┐│
   │  │ su /media disk │                          │  APScheduler      ││
   │  └───────────────┘                          │  - Motore Notturno ││
   │                                              │  - Cecchino Tech   ││
   │                                              │  - Cecchino Auto   ││
   │                                              └────────┬──────────┘│
   │                                                        │          │
   │  ┌──────────────────────────────────────────────────┐ │          │
   │  │  API REST (/api/opportunities, /api/trends, ...)  │◀┘          │
   │  └───────────────────────┬────────────────────────────┘          │
   └──────────────────────────┼──────────────────────────────────────┘
                               │ JSON
                               ▼
                    ┌───────────────────────┐
                    │  FRONTEND (Next.js)    │
                    │  Live Sniper Feed      │
                    │  Market Intelligence   │
                    │  Automations panel     │
                    └───────────────────────┘

                    ┌───────────────────────┐
                    │  PostgreSQL (Docker)   │
                    │  - target_models       │
                    │  - live_opportunities_*│
                    │  - market_trends       │
                    │  - price_history       │
                    │  - sent_alerts / deals │
                    └───────────────────────┘
                    immagini → /media su disco (servite da FastAPI)
```

**Principio cardine**: il backend non naviga con un browser headless. Subito.it è una SPA che carica gli annunci via un'API JSON interna (`hades.subito.it/v1/search/items`), individuata per reverse engineering (`scripts/api_explorer.py`). Interrogarla direttamente restituisce l'intero annuncio (titolo, prezzo, descrizione, immagini, venditore, features strutturate) in pochi millisecondi, senza il costo e la fragilità di Playwright/Selenium.

### Split routing (ottimizzazione costi proxy)

Le chiamate all'API `hades` passano da un **proxy residenziale rotante** (IPRoyal) per evitare ban IP sulle ricerche ripetute; il download delle immagini invece va **sempre in connessione diretta**, perché la CDN di Subito non blocca il traffico immagini e instradarle sul proxy a consumo sprecherebbe budget. Questo è implementato con due client `httpx` separati in `backend/scrapers/subito.py` (`_make_api_client` vs `_make_cdn_client`).

---

## Struttura del codice

```
backend/
├── main.py                  # entrypoint FastAPI, CORS, lifespan (avvio/stop scheduler)
├── tasks.py                 # cuore business: motori, persistenza, margini, dedup, IQR
├── api/
│   ├── health.py            # GET /health
│   ├── scrape.py            # endpoint manuali di test (scrape on-demand, nightly on-demand)
│   └── data.py               # GET /api/opportunities, GET /api/trends (letti dal frontend)
├── core/
│   ├── config.py             # Settings da .env (DATABASE_URL, media, proxy, Telegram)
│   ├── database.py           # layer DB su psycopg (pool + query-builder compat) + storage immagini su disco
│   └── scheduler.py          # APScheduler: registra i 3 job ricorrenti
├── scrapers/
│   ├── base.py                # interfaccia astratta ScrapedListing / BaseScraper (Strategy pattern)
│   ├── subito.py               # scraper Subito: fetch hades, parsing, pHash, split routing
│   └── nlp_parser.py           # pre-parsing regex: km/anno, allestimenti, difetti, urgenza
└── services/
    ├── reads.py                # query di lettura + intelligence (score, trattativa, time-to-sale)
    ├── scoring.py              # Deal Score, offerta suggerita, penalità difetti, radar riparazioni
    ├── notifications.py        # notifiche Telegram (nuove opportunità + cali di prezzo)
    └── garbage_collector.py    # servizio decadimento annunci (schedulato) → alimenta il time-to-sale

database/
└── 01…15_*.sql                # migrazioni incrementali applicate in ordine numerico

scripts/
├── api_explorer.py             # reverse engineering / debug dell'endpoint hades
├── run_backfill.py             # "aspirapolvere": scraping storico profondo per ogni target
├── garbage_collector.py        # verifica annunci scaduti/rimossi e li marca
├── seed_target_models.py       # seed/upsert dei modelli da monitorare
├── seed_car_target.py          # seed di un target auto singolo (legacy)
└── test_sniper_auto.py         # collaudo manuale dello split routing sul verticale auto

frontend/
└── src/
    ├── app/
    │   ├── page.tsx             # dashboard "FlipRadar" (Live Sniper / Market Intelligence / Pipeline P&L / Automations)
    │   ├── scanner/page.tsx     # vista tabellare alternativa (dati mock, non collegata al menu)
    │   └── calculator/page.tsx  # calcolatore margini standalone
    ├── components/               # sidebar, grafico trend, calcolatore margine
    └── lib/
        ├── api.ts                # client fetch verso il backend FastAPI (opportunità, trends, deals)
        └── flipradar-data.ts     # formattazione EUR, colori margine/score, tempo relativo
```

---

## Modello dati

Lo schema completo e riproducibile vive in **`database/selfhosted/init.sql`** (applicato automaticamente da Docker al primo avvio). Le tabelle principali:

| Tabella | Scopo |
|---|---|
| `target_models` | **Flotta di scraping dinamica**: ogni riga è un modello da monitorare (query di ricerca + `strict_filters` JSONB come anno/km/cambio). Aggiungere un target = una `INSERT`, niente redeploy. |
| `products` | Catalogo dei modelli tracciati (brand, categoria, specs). |
| `live_opportunities_auto` / `live_opportunities_tech` | **Table-per-type**: annunci trovati dal Cecchino, separati per verticale (auto vs tech) per isolare volumi e schema (le auto hanno colonne aggiuntive: anno, km, cambio, carburante). |
| `market_trends` | Snapshot giornaliero di media/min/max/volume prezzi, **isolato per `target_id`** (non per semplice nome modello: due generazioni della stessa auto non si mescolano). |
| `price_history` | Storico dei cali di prezzo per singolo annuncio (alimenta il "Price Drop Alert"). |
| `sent_alerts` | Registro delle notifiche Telegram inviate: vincolo `(listing_id, alert_type)` per non rinotificare mai lo stesso annuncio per lo stesso motivo. |
| `deals` | **Pipeline P&L**: il gestionale degli affari seguiti (ciclo di vita dal feed alla rivendita, con prezzi e costi reali → profitto netto). |
| `/media` su disco | Le gallerie fotografiche riscaricate (i link originali di Subito scadono), salvate su filesystem e servite da FastAPI su `/media/...`. |

I file `database/01`→`15_*.sql` restano come **storico** dell'evoluzione dello schema (erano le migrazioni incrementali dell'istanza Supabase); per un'installazione nuova fa fede il singolo `selfhosted/init.sql`. Lo schema è pieno Postgres (enum, JSONB, trigger, indici GIN) — nessuna dipendenza da Supabase, RLS/Auth rimosse perché l'unico client che si connette è il backend, fidato.

---

## Feature principali

### 1. Cecchino Live (Sniper)
Job schedulato che legge la flotta attiva da `target_models`, interroga `hades` **ordinando per data** (i più recenti prima, così ogni giro vede gli ultimi pubblicati), scarica le immagini solo per gli annunci nuovi e fa l'upsert su `live_opportunities_*`. Cadenze differenziate: **tech ogni 5 minuti** (su Subito il primo che scrive vince, e una pagina API tech costa pochissimo proxy), **auto ogni 15 minuti** (volumi e download immagini più pesanti). I due verticali hanno scope disgiunto per non doppio-scansionare.

### 2. Motore Notturno (Market Intelligence)
Job giornaliero (03:00 Europe/Rome) che ricalcola la media di mercato per ogni target attivo applicando la **regola IQR (1.5× interquartile range)** per scartare i prezzi anomali (annunci-truffa, refurbished a prezzo pieno, errori di battitura) prima di fare la media — vedi `filter_price_outliers` in `backend/tasks.py`.

### 3. Calcolo margine in tempo reale
Ogni opportunità viene arricchita, in fase di lettura (`backend/services/reads.py`), con la media di mercato del suo `target_id` (fallback sul nome modello per gli snapshot legacy) per calcolare margine assoluto (€) e percentuale, mostrati nella dashboard con badge colorati (Alto margine / Margine medio / Sotto media).

### 4. NLP Parser (regex, zero dipendenze esterne) — auto **e** tech
`backend/scrapers/nlp_parser.py` analizza titolo e descrizione di ogni annuncio per estrarre segnale che l'API di Subito non fornisce o fornisce sporco. È **bi-verticale**:
- **Auto**: km/anno di fallback; **allestimenti/optional** normalizzati per sinonimi (es. "M Sport"/"MSport"/"pacchetto M" → `M-Sport`); **difetti** (frizione, graffi, grandine, spia motore, incidentata, motore fuso...); **urgenza** (trasferimento, svendita, allargamento famiglia...).
- **Tech/iPhone**: **taglio di memoria** (64/128/256/512GB/1TB), **salute batteria** ("batteria 87%", "battery health 90%"), **corredo** (scatola, fattura, AppleCare, "pari al nuovo", batteria cambiata), **difetti** (schermo/vetro rotto, iCloud bloccato, Face ID, "per ricambi").
- **Esclusione dall'IQR**: gli annunci non-sani vengono tenuti fuori dal calcolo della media di mercato per non inquinarla — auto incidentata/fusa, iPhone con schermo rotto / iCloud bloccato / "per ricambi" (il loro prezzo non fa mercato del funzionante).

### 5. Anti-ripubblicazione via Perceptual Hash (pHash)
Molti venditori cancellano e ripubblicano lo stesso annuncio per sembrare "nuovi" e scalare la classifica. Il backend calcola il **pHash a 64 bit** (`imagehash.phash`) della prima foto scaricata; se lo stesso hash ricompare sotto un nuovo `listing_url`, il sistema riconosce la ripubblicazione e **aggiorna il record esistente** invece di duplicarlo, preservando lo storico prezzi.

### 6. Shadow Dealer detection
Un venditore che si dichiara "privato" ma ha più di 3 annunci attivi contemporaneamente nella stessa tabella viene riclassificato automaticamente `finto_privato` (`apply_shadow_dealer` in `tasks.py`) — utile per riconoscere concessionari mascherati che offrono margini di trattativa diversi da un vero privato.

### 7. Price Drop Alert
Quando un annuncio già tracciato scende di prezzo, il vecchio prezzo viene spostato in `original_price` e l'evento viene storicizzato in `price_history`; il frontend evidenzia il calo nella card espansa dell'annuncio.

### 8. Garbage Collector (schedulato)
Servizio (`backend/services/garbage_collector.py`, con wrapper CLI in `scripts/`) che gira **ogni notte alle 04:30** nello scheduler: verifica se gli annunci ancora "attivi" a DB sono raggiungibili sul sito reale (404/410 o redirect fuori dalla pagina annuncio) e li marca `venduto_rimosso`. Oltre a pulire il feed, la differenza `found_at → data di rimozione` è il **sensore del time-to-sale** (vedi Data Intelligence).

### 9. Notifiche Telegram (nuove opportunità + cali di prezzo)
Al termine di ogni giro sniper, `backend/services/notifications.py` invia su Telegram le opportunità **nuove** con margine sopra soglia e i **cali di prezzo** rilevanti — con foto, prezzo vs media, difetti/urgenza e link diretto. Un bot, **due chat separate** (una per il verticale iPhone, una per l'auto). Deduplicazione persistente su `sent_alerts`: lo stesso annuncio non viene mai rinotificato. Config assente → no-op silenzioso, lo Sniper funziona comunque.

### 10. Deep Backfill
`scripts/run_backfill.py` è la modalità "aspirapolvere": per ogni target pagina in profondità l'intero risultato di ricerca (non solo il primo blocco come lo Sniper live) per popolare velocemente lo storico iniziale di un nuovo modello tracciato, senza scaricare immagini (le riempirà lo Sniper sui nuovi incontri).

### 11. Resilienza anti-ban
Le chiamate a `hades` sono avvolte in retry con backoff esponenziale (`tenacity`) su status transitori (403/429/500), cambiando nodo del proxy rotante a ogni tentativo.

---

## Data Intelligence: dal dato alla decisione d'acquisto

Lo scraping raccoglie i dati; questo layer li trasforma in **decisioni di acquisto profittevoli**. Tutta l'intelligence è calcolata in lettura (`backend/services/reads.py` + `scoring.py`), con euristiche trasparenti e nessun modello ML da addestrare.

### Deal Score (0–100)
Il margine % da solo ordina male il feed: un +25% da un finto privato, annuncio vecchio di 3 settimane e "da rivedere" vale meno di un +18% pubblicato un'ora fa da un privato che "svende causa trasferimento". Il **Deal Score** combina in un unico punteggio: margine (fino a 55 pt, satura a +33%), freschezza dell'annuncio, urgenza dichiarata, tipo venditore (privato > finto_privato), calo di prezzo già avvenuto, penalità difetti, salute batteria e corredo (tech). Il feed è ordinabile per Score, con breakdown leggibile di ogni contributo.

### Assistente di trattativa
Nella card espansa di ogni opportunità: **prezzo di offerta suggerito** (media di mercato − margine obiettivo − penalità difetti − costi riparazione, arrotondato), **giorni online** (un annuncio invenduto da 24 giorni si tratta meglio), storico cali di prezzo, **storico venditore** (quanti annunci attivi ha davvero), e un tasto per portare l'affare nella pipeline P&L.

### Radar riparazioni (tech)
Gli iPhone "schermo rotto" o "batteria da cambiare" sono un business a parte: prezzo stracciato + costo di riparazione noto = margine spesso superiore al flip semplice. Il sistema stima il costo (batteria ~79€, schermo 150–300€ per fascia di modello, vetro posteriore ~120€) e ricalcola il **margine netto post-riparazione**, mostrando il badge "🔧 da riparare" sul feed.

### Segmentazione per variante (tech)
Con l'NLP tech, la media di mercato è isolata **per (modello, taglio di memoria)**: un iPhone 13 128GB e un 256GB non finiscono più nella stessa media (differiscono di 60–90€). È la modifica che rende i margini tech affidabili, cioè il numero su cui rischi soldi veri.

### Valutazione km-aware (auto)
Una regressione lineare `prezzo ~ km` per singolo target (accettata solo con ≥8 campioni e pendenza negativa) stima il **prezzo atteso di quella specifica auto** dati i suoi km — invece di confrontarla con la media indistinta della categoria. Il margine reale è calcolato contro questo valore.

### Time-to-sale e prezzi di rivendita
Dai `venduto_rimosso` del Garbage Collector si misura in **quanti giorni ruota** ogni modello (liquidità reale): un iPhone 13 con margine 18% che gira in 4 giorni batte un 14 Pro con margine 25% invenduto da 3 settimane. La distribuzione dei prezzi attivi produce i **prezzi di rivendita suggeriti**: 25° percentile per una vendita rapida, mediana per il prezzo pieno. Entrambi visibili in Market Intelligence per modello.

### Pipeline P&L
Il gestionale dell'impresa (`backend/api/deals.py` + schermata dedicata): ogni affare seguito attraversa gli stati `interessante → contattato → offerta → comprato → in_vendita → venduto`, registrando prezzo pagato, costi accessori (riparazioni, trasporto...) e prezzo di rivendita → **profitto netto reale**. Doppio valore: è la contabilità dell'impresa e chiude il feedback loop, confrontando il margine stimato dal bot con quello effettivamente incassato.

---

## Come funziona: il flusso end-to-end

1. **APScheduler** (`backend/core/scheduler.py`), avviato nel lifespan di FastAPI, tiene attivi 4 job:
   - `nightly_batch` → `run_nightly_batch_all_products()` alle 03:00
   - `garbage_collector` → `run_garbage_collector()` alle 04:30 (annunci rimossi → time-to-sale)
   - `sniper_live` → `run_sniper_all_products(category="smartphone")` ogni **5'**
   - `sniper_auto_live` → `run_sniper_all_products(category="automobile", pages=1)` ogni 15'
2. Ogni job legge da **`target_models`** i target attivi (`is_active = true`) invece di avere modelli hardcoded nel codice.
3. Per ciascun target, **`SubitoScraper.search_text`** interroga `hades.subito.it` (via proxy, ordinando per data) applicando prezzo minimo/massimo anti-spam, strict match sul titolo e `strict_filters` nativi (anno/km/cambio per le auto, **taglio memoria/batteria** per il tech).
4. Ogni annuncio grezzo passa dal **parser NLP bi-verticale** per estrarre segnale aggiuntivo (km/anno, storage/batteria, features, difetti, urgenza, flag di esclusione IQR).
5. **`persist_opportunities`** instrada l'annuncio sulla tabella corretta (`_auto` / `_tech`), deduplica su `listing_url`, scarica le immagini (solo per i nuovi) calcolandone il pHash, rileva le ripubblicazioni via pHash e — per le auto — applica la Shadow Dealer detection prima dell'insert.
6. Gli annunci già noti vengono aggiornati (`updated_at`); se il prezzo è sceso, il vecchio prezzo passa a `original_price` e viene storicizzato in `price_history`.
7. Al termine del giro, le nuove opportunità sopra soglia e i cali di prezzo vengono **notificati su Telegram** (con dedup su `sent_alerts`).
8. Una volta al giorno, il **Motore Notturno** ricalcola media/min/max/volume per target con pulizia IQR e salva lo snapshot in `market_trends`; il **Garbage Collector** marca i venduti/rimossi.
9. Il **frontend** interroga `GET /api/opportunities` e `GET /api/trends`: il backend (`services/reads.py` + `scoring.py`) arricchisce ogni opportunità con margine, **Deal Score**, assistente di trattativa, radar riparazioni e valutazione km-aware, e la mostra nella dashboard **Live Sniper** (ordinabile per Score). Gli affari seguiti finiscono nella **Pipeline P&L**.

---

## Tecnologie utilizzate

**Backend**
- **Python 3.11+**, **FastAPI** — API REST asincrona
- **httpx** (async) — client HTTP per l'API `hades` e per la CDN immagini
- **tenacity** — retry con exponential backoff sulle chiamate esterne
- **APScheduler** (`AsyncIOScheduler`) — scheduling dei motori in-process, senza Celery/cron esterni
- **psycopg 3** (+ `psycopg_pool`) — accesso a PostgreSQL con pool di connessioni; un layer compatibile in `backend/core/database.py` mantiene l'API `.table().select()...` del vecchio client
- **Pillow + imagehash** — perceptual hashing delle immagini
- **python-dotenv** — configurazione da `.env`

**Frontend**
- **Next.js 16** (App Router) + **React 19** + **TypeScript**
- **Tailwind CSS 4**
- **Recharts** — grafici (componente `market-trend-chart.tsx`)
- **lucide-react** — iconografia

**Dati / infrastruttura**
- **PostgreSQL self-hosted** (container Docker) come datastore; immagini su **filesystem** servite da FastAPI
- **Docker Compose** per far girare Postgres + backend con un comando (locale o VPS)
- **Proxy residenziale rotante IPRoyal** per le chiamate di ricerca (evitare rate-limit/ban IP)

---

## Setup e comandi

### Prerequisiti
- **Docker + Docker Compose** (il modo consigliato: Postgres + backend con un comando)
- Node.js 18+ (solo per il frontend)
- (Opzionale ma consigliato) credenziali di un proxy residenziale rotante e un bot Telegram

### 1. Avvio con Docker (consigliato)

```bash
# dalla root del progetto
cp .env.example .env                  # imposta POSTGRES_PASSWORD (e PUBLIC_MEDIA_BASE_URL in prod)
cp backend/.env.example backend/.env  # proxy IPRoyal + Telegram (facoltativi)

docker compose up -d                  # avvia Postgres + backend
docker compose logs -f backend        # segui i log dello Sniper
```

Al primo avvio Postgres esegue automaticamente `database/selfhosted/init.sql` (schema completo + target pilota). L'API è su `http://localhost:8000` (`/docs` per la doc automatica), le immagini su `http://localhost:8000/media/...`.

Sul **VPS Hetzner** è lo stesso identico comando: installa Docker, clona il repo, imposta `PUBLIC_MEDIA_BASE_URL` col dominio/IP pubblico in `.env`, e `docker compose up -d`.

### 1-bis. Avvio senza Docker (sviluppo)

Serve un PostgreSQL locale. Poi:

```bash
python -m venv .venv
source .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# crea il DB e applica lo schema
createdb reseller
psql -d reseller -f database/selfhosted/init.sql

cp backend/.env.example backend/.env  # imposta DATABASE_URL se diverso dal default
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/reseller"

uvicorn backend.main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Dashboard su `http://localhost:3000` (punta di default a `http://localhost:8000`; override con `NEXT_PUBLIC_API_BASE_URL`).

### 3. Popolare la flotta di target

Lo schema iniziale contiene già due target pilota (Golf GTI, iPhone 14). Per aggiungerne/aggiornarne:

```bash
python scripts/seed_target_models.py
```

### 4. Backfill iniziale (opzionale ma consigliato)

Per non aspettare 5-15 minuti alla volta per popolare lo storico:

```bash
python scripts/run_backfill.py 10 automobile     # 10 pagine per target, solo auto
python scripts/run_backfill.py                   # tutte le categorie, default 10 pagine
```

### 5. Notifiche Telegram (consigliato)

Crea un bot con [@BotFather](https://t.me/BotFather), copia il token in `TELEGRAM_BOT_TOKEN` e ricava i chat ID (scrivi al bot, poi `https://api.telegram.org/bot<TOKEN>/getUpdates`). Usa **due chat/gruppi separati** per i due verticali:

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID_TECH=-100xxxxxxxxx   # canale/gruppo iPhone
TELEGRAM_CHAT_ID_AUTO=-100yyyyyyyyy   # canale/gruppo auto
```

Da qui in poi ogni giro dello Sniper notifica le nuove opportunità sopra soglia e i cali di prezzo.

### 6. Garbage Collector on-demand (facoltativo)

Gira già automaticamente ogni notte nello scheduler; il wrapper CLI serve per lanciarlo a mano:

```bash
python scripts/garbage_collector.py             # tutte le categorie
python scripts/garbage_collector.py automobile   # solo un verticale
```

### 7. Backup del database

```bash
./scripts/backup_db.sh          # pg_dump compresso in ./backups/ (da mettere in cron sul VPS)
```

### 8. Test

```bash
python scripts/test_intelligence.py   # NLP (tech+auto) + scoring, senza dipendenze DB
python scripts/test_db_shim.py        # generazione SQL del layer DB (richiede psycopg)
```

---

## Configurazione (.env)

File: `backend/.env` per i segreti dell'app; `.env` (root) per docker-compose. Vedi `backend/.env.example` e `.env.example`.

| Variabile | Dove | Descrizione |
|---|---|---|
| `DATABASE_URL` | backend | Connessione Postgres (`postgresql://user:pass@host:5432/reseller`). Con Docker la imposta il compose. |
| `MEDIA_ROOT` | backend | Cartella dove salvare le immagini (default `./media`; in Docker `/data/media`) |
| `PUBLIC_MEDIA_BASE_URL` | backend/root | URL pubblico da cui il browser carica le immagini (in prod: dominio/IP del VPS) |
| `POSTGRES_PASSWORD` | root | Password del Postgres in container (compose) |
| `PROXY_HOST` / `PROXY_PORT` / `PROXY_USER` / `PROXY_PASS` | backend | Proxy residenziale rotante per le chiamate a `hades`; se vuoti, l'API viene chiamata in diretta |
| `TELEGRAM_BOT_TOKEN` | No | Token del bot Telegram; se vuoto le notifiche sono disattivate |
| `TELEGRAM_CHAT_ID_TECH` / `TELEGRAM_CHAT_ID_AUTO` | No | Chat di destinazione per i due verticali |
| `ALERT_MIN_MARGIN_PCT` | No | Soglia margine % per notificare una nuova opportunità (default 20) |
| `ALERT_MIN_DROP_PCT` | No | Calo prezzo % minimo per notificare un ribasso (default 10) |
| `ENVIRONMENT` | No | `development` di default |
| `CORS_ORIGINS` | No | Origini frontend ammesse, comma-separated (default `localhost:3000`) |

---

## API REST

| Endpoint | Metodo | Descrizione |
|---|---|---|
| `/health` | GET | Health check |
| `/api/opportunities?category=smartphone\|automobile&limit=60` | GET | Feed Live Sniper arricchito: margine, **Deal Score**, assistente trattativa, radar riparazioni, valutazione km-aware |
| `/api/opportunities/{id}?category=...` | PATCH | Aggiorna lo stato di un'opportunità (es. `visto` all'apertura) |
| `/api/trends?category=smartphone\|automobile` | GET | KPI di verticale: annunci attivi, prezzo medio, **time-to-sale**, serie storica, classifica per modello con liquidità e prezzi di rivendita |
| `/api/deals` | GET / POST | Pipeline P&L: lista affari / crea un affare dal feed |
| `/api/deals/summary` | GET | KPI P&L: capitale investito, profitto realizzato, margine reale medio |
| `/api/deals/{id}` | PATCH / DELETE | Aggiorna stato/prezzi/costi di un affare, oppure eliminalo |
| `/api/scrape/test-subito?query=...&category=...&pages=...` | GET | Scraping manuale on-demand (debug/test, non passa dallo scheduler) |
| `/api/scrape/run-nightly?query=...&category=...` | GET | Esecuzione manuale del Motore Notturno per una singola query (debug/test) |

---

## Script operativi

| Script | Quando usarlo |
|---|---|
| `scripts/seed_target_models.py` | Bootstrap o aggiornamento della flotta di modelli da monitorare |
| `scripts/run_backfill.py [max_pages] [category]` | Popolamento storico profondo di un nuovo target |
| `scripts/garbage_collector.py [category]` | Lancio manuale del GC (gira già ogni notte nello scheduler) |
| `scripts/test_intelligence.py` | Test delle funzioni pure NLP (tech+auto) e scoring, senza dipendenze DB |
| `scripts/api_explorer.py "query"` | Debug/reverse engineering dell'endpoint `hades` di Subito |
| `scripts/test_sniper_auto.py` | Collaudo manuale end-to-end dello split routing sul verticale auto (log dettagliati su proxy, filtri, CDN) |
| `scripts/seed_car_target.py` | Seed legacy di un singolo target auto tramite `products.specs` (superato da `target_models`) |

---

## Note di design / limiti noti

- **`frontend/src/app/page.tsx`** è la dashboard reale in uso ("FlipRadar"), con 4 schermate (Live Sniper, Market Intelligence, Pipeline P&L, Automations) collegate alle API live. Le pagine `frontend/src/app/scanner` e `frontend/src/app/calculator` (con il componente `Sidebar`) restano nel repo ma lavorano su **dati mock** e non sono raggiungibili dal menu della dashboard principale: sono un'interfaccia precedente non più collegata al flusso.
- Il pannello **Automations** della dashboard è ancora in parte dimostrativo (il pulsante "Force Run" e il cambio intervallo non pilotano davvero lo scheduler): è il prossimo candidato al collegamento reale via endpoint di controllo job.
- Lo schema nuovo si applica da `database/selfhosted/init.sql` (automatico al primo avvio di Docker); non esiste ancora un runner di migrazioni versionato per gli aggiornamenti incrementali di uno schema già popolato.
- I **costi di riparazione e le penalità difetti** in `backend/services/scoring.py` sono euristiche dichiarate: vanno tarate sull'esperienza reale registrata nella Pipeline P&L.
- Lo scheduler gira **in-process** nell'app FastAPI: in produzione avvia un solo worker (il default del compose), altrimenti ogni worker lancerebbe una copia dei job duplicando lo scraping.
- L'accesso ai dati passa da un **layer compatibile** (`backend/core/database.py`) che replica l'API del client Supabase su un pool psycopg: le funzioni sync girano nei thread (`asyncio.to_thread`) senza bloccare l'event loop, e il pool è thread-safe. Migrare a un altro Postgres = cambiare `DATABASE_URL`.
- Le **immagini** stanno sul filesystem (`/media`), servite da FastAPI: per un backup completo salva sia il `pg_dump` (`scripts/backup_db.sh`) sia il volume `media`.
