# Architettura

```
                         ┌─────────────────────────┐
                         │   hades.subito.it        │
                         │  (API JSON interna SPA)  │
                         └────────────┬─────────────┘
                                      │ HTTP/JSON (curl_cffi diretto, a ritmo controllato)
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

## Ritmo da un solo IP (niente proxy)

Dal 2026-10-02 il progetto non usa servizi a pagamento: il proxy residenziale
IPRoyal è dismesso e tutto va in **connessione diretta**. Invece di aggirare il
rate limit con IP rotanti, si resta sotto la soglia:

- **`HadesPacer`** (`backend/scrapers/subito.py`): pausa minima globale tra due
  chiamate a `hades` (`SCRAPER_MIN_GAP_S`, ±25% di jitter), condivisa da tutti
  i job. Su **403/429** niente retry: pausa di `SCRAPER_BLOCK_COOLDOWN_S`
  (raddoppia se il blocco si ripete, max 4h), ritmo dimezzato, e il giro si
  ferma. Ogni richiesta riuscita riporta il ritmo verso il minimo del 2%.
- **Paginazione fino a ricongiungersi**: lo Sniper chiede pagina 1 (ordine per
  data) e va avanti solo finché la pagina è piena e il suo annuncio più vecchio
  è stato pubblicato dopo la scansione precedente del target (`last_scanned`).
  Le chiamate crescono col volume pubblicato, non con la frequenza dei giri.
- **Buchi misurati**: se un target arriva al tetto di pagine senza
  ricongiungersi, il giro lo conta in `scrape_runs.gaps` = annunci persi,
  cadenza troppo lenta. È il criterio di sufficienza: zero buchi.
- Il limite reale dipende dall'IP: si misura con `scripts/probe_rate_limit.py`.

**Misure del 2026-10-02 (PC Windows, rete di casa):** rampa da 1 richiesta/60s
fino a 1/s, 8 richieste per gradino → **nessun blocco**. Volume pubblicato:
"iphone" ~1.400 annunci/giorno; il modello più vivace (iPhone 13) ~290/giorno.
Stock attivo: ~67.800 risultati "iphone", ~51.600 sopra i 50€ (sotto sono quasi
tutti accessori). **hades non restituisce oltre 10.000 risultati per ricerca**
(start ≥ 10000 → vuoto): per vedere tutto lo stock la ricerca va spezzata in
fasce di prezzo (`ps`/`pe`, inclusivi), ognuna sotto il tetto.

## Copertura del tech: ricerca ampia + inventario

Il criterio è coprire la **totalità** degli annunci iPhone, perché le metriche
siano affidabili. Due giri, entrambi in `backend/services/sweep.py`:

- **Sweep** (ogni 15'): UNA ricerca `"iphone"` ordinata per data, all'indietro
  fino al giro precedente. Ogni annuncio pubblicato passa una volta, qualunque
  modello sia: ~1 richiesta per giro invece delle 36 del vecchio Sniper per
  target (che si sovrapponevano e lasciavano fuori i modelli senza target).
- **Assegnazione al target del modello** (`match_target`): un "iPhone 13 Pro"
  trovato cercando "iphone" va al target *iPhone 13 Pro*. Prima finiva sotto
  la query che l'aveva trovato ("iPhone 13"), mescolando i modelli nelle
  statistiche. Gli iPhone senza target si salvano con `target_id` NULL.
- **Inventario notturno** (`reconcile_inventory`, 01:30): sfoglia tutto lo
  stock per fasce di prezzo (~540 richieste). Aggiorna i prezzi di **tutti**
  gli annunci (storico ribassi completo) e trova i candidati venduti: attivi
  nel DB ma assenti dall'inventario. Solo quelli si verificano pagina per
  pagina. Sostituisce il Garbage Collector per il tech, che costava una
  richiesta per annuncio attivo.
- **Recupero iniziale**: `scripts/deep_sweep.py` = lo stesso giro d'inventario,
  da lanciare a mano la prima volta.

Le auto restano sullo Sniper per target (troppi modelli e volumi per una
ricerca unica) con il Garbage Collector classico.

Il download delle immagini va su un client separato (`_make_cdn_client`,
httpx diretto): la CDN non è protetta da Akamai.

## Flusso end-to-end

1. **APScheduler** (`backend/core/scheduler.py`), avviato nel lifespan di
   FastAPI, tiene attivi 5 job:
   - `sniper_live` → `run_sweep("smartphone")` ogni **15'** (`SNIPER_TECH_INTERVAL_MIN`)
   - `sniper_auto_live` → `run_sniper_all_products("automobile")` ogni **30'** (`SNIPER_AUTO_INTERVAL_MIN`)
   - `inventory_tech` → `reconcile_inventory("smartphone")` alle 01:30
   - `nightly_batch` → `run_nightly_batch_all_products()` alle 03:00 (tech: medie dal DB, zero richieste)
   - `garbage_collector` → `run_garbage_collector("automobile")` alle 04:30
2. I target attivi stanno in **`target_models`** (DB-driven, non hardcoded).
3. Tech: ricerca ampia (vedi sopra). Auto: per ogni target **`SubitoScraper.search_text`** interroga `hades` (curl_cffi
   diretto, a ritmo del pacer, ordine per data, pagine fino a ricongiungersi con
   la scansione precedente) applicando prezzo anti-spam, strict match e
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
8. Notte: **Inventario tech** e **Garbage Collector auto** (venduti/rimossi →
   time-to-sale), poi **Motore Notturno** (medie IQR → `market_trends`).
   Età e tempo di vendita partono da `published_at` (pubblicazione su Subito,
   migrazione 19) quando c'è, altrimenti da `found_at`.
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
servite da FastAPI; Docker Compose (Postgres + backend). Nessun servizio a
pagamento.
