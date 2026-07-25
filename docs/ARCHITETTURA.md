# Architettura

```
                         ┌─────────────────────────┐
                         │   hades.subito.it        │
                         │  (API JSON interna SPA)  │
                         └────────────┬─────────────┘
                                      │ HTTP/JSON (curl_cffi + proxy residenziale)
                                      ▼
   ┌───────────────────────────────────────────────────────────────┐
   │                        BACKEND (FastAPI)                        │
   │  ┌───────────────┐   ┌───────────────────┐   ┌──────────────┐  │
   │  │  SubitoScraper │──▶│   NLP Parser       │──▶│  tasks.py    │  │
   │  │ (split routing)│   │ (regex, 0 dipend.) │   │ (motori +    │  │
   │  └───────────────┘   └───────────────────┘   │  business)   │  │
   │         │ immagini (CDN diretta, httpx)        └──────┬───────┘  │
   │         ▼                                             ▼          │
   │  ┌───────────────┐                          ┌──────────────────┐│
   │  │ pHash + /media │                          │  APScheduler      ││
   │  └───────────────┘                          │  notturno/cecchini ││
   │                                              │  + garbage collect ││
   │  ┌──────────────────────────────────────┐   └──────────┬────────┘│
   │  │  API REST (/api/opportunities, ...)   │◀─────────────┘         │
   │  └───────────────────┬──────────────────┘                        │
   └──────────────────────┼───────────────────────────────────────────┘
                          │ JSON                    ┌──────────────────────┐
                          ▼                         │  PostgreSQL (Docker)  │
               ┌───────────────────────┐           │  target_models        │
               │  FRONTEND (Next.js)    │           │  live_opportunities_* │
               │  Live Sniper           │           │  market_trends        │
               │  Market Intelligence   │           │  price_history        │
               │  Pipeline P&L          │           │  sent_alerts / deals  │
               └───────────────────────┘           │  scrape_runs          │
                    immagini → /media su disco       └──────────────────────┘
```

## Principio cardine

Il backend **non naviga con un browser headless**. Subito.it è una SPA che
carica gli annunci via un'API JSON interna (`hades.subito.it/v1/search/items`),
individuata per reverse engineering (`scripts/api_explorer.py`). Interrogarla
direttamente restituisce l'intero annuncio (titolo, prezzo, descrizione,
immagini, venditore, features) in pochi millisecondi, senza il costo e la
fragilità di Playwright/Selenium.

## Anti-bot: curl_cffi (impronta TLS)

`hades` è protetto da **Akamai Bot Manager**, che blocca con 403 i client
dall'impronta TLS "non-browser" come `httpx` puro. Le chiamate di ricerca usano
quindi **curl_cffi** con impersonazione (Safari/Firefox), che imita il
fingerprint di un browser reale senza aprirne uno. Il pool di profili viene
ruotato a caso per target (resilienza se Akamai flagga un profilo).

## Split routing (ottimizzazione costi proxy)

Le chiamate all'API `hades` passano da un **proxy residenziale rotante**
(IPRoyal) per evitare ban IP; il download delle immagini va **sempre in
connessione diretta** (`httpx`), perché la CDN non blocca il traffico immagini e
instradarle sul proxy a consumo sprecherebbe budget. Due client separati in
`backend/scrapers/subito.py` (`_make_api_client` curl_cffi/proxy vs
`_make_cdn_client` httpx/diretto).

## Flusso end-to-end

1. **APScheduler** (`backend/core/scheduler.py`), avviato nel lifespan di
   FastAPI, tiene attivi 4 job:
   - `nightly_batch` → `run_nightly_batch_all_products()` alle 03:00
   - `garbage_collector` → `run_garbage_collector()` alle 04:30 (rimossi → time-to-sale)
   - `sniper_live` → `run_sniper_all_products("smartphone")` ogni **5'**
   - `sniper_auto_live` → `run_sniper_all_products("automobile")` ogni **15'**
2. Ogni job legge i target attivi da **`target_models`** (DB-driven, non hardcoded).
3. Per ogni target, **`SubitoScraper.search_text`** interroga `hades` (curl_cffi
   via proxy, ordine per data) applicando prezzo anti-spam, strict match e
   `strict_filters` nativi (anno/km/cambio auto; memoria/batteria tech).
4. Ogni annuncio passa dal **parser NLP** (km/anno, storage/batteria, features,
   difetti, urgenza, esclusione IQR) e dal **resolver di variante canonica**.
5. **`persist_opportunities`** instrada su `_auto`/`_tech`, deduplica su
   `listing_url`, scarica immagini (solo nuovi) + pHash, rileva ripubblicazioni,
   e (auto) applica lo Shadow Dealer.
6. Gli annunci noti si aggiornano; sui cali di prezzo: `original_price` +
   `price_history`.
7. Fine giro: **notifiche Telegram** (nuove opportunità + cali) con dedup, e
   **record di salute** (`scrape_runs`) con eventuale alert down/ripristino.
8. Notte: **Motore Notturno** (medie IQR → `market_trends`) e **Garbage
   Collector** (venduti/rimossi).
9. Il **frontend** legge `/api/opportunities` e `/api/trends`; il backend
   (`services/reads.py` + `scoring.py` + `valuation.py`) arricchisce ogni
   opportunità con margine, valore equo, Deal Score, assistente di trattativa.

## Tecnologie

**Backend** — Python 3.11+, FastAPI, curl_cffi (anti-Akamai) + httpx, tenacity
(retry), APScheduler (scheduling in-process), psycopg 3 + psycopg_pool,
Pillow + imagehash (pHash), python-dotenv.

**Frontend** — Next.js 16 (App Router), React 19, TypeScript, Tailwind CSS 4,
Recharts, lucide-react.

**Dati / infra** — PostgreSQL self-hosted (Docker); immagini su filesystem
servite da FastAPI; Docker Compose (Postgres + backend); proxy residenziale
rotante IPRoyal.
