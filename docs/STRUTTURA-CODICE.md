# Struttura del codice

```
backend/
├── main.py                  # entrypoint FastAPI, CORS, mount /media, lifespan (scheduler)
├── tasks.py                 # cuore business: motori, persistenza, margini, dedup, IQR, salute
├── api/
│   ├── health.py            # GET /health, GET /health/scraper (stato raccolta)
│   ├── scrape.py            # endpoint manuali di test (scrape/nightly on-demand)
│   ├── data.py              # GET /api/opportunities (+PATCH stato), GET /api/trends
│   └── deals.py             # Pipeline P&L: CRUD affari + /summary
├── core/
│   ├── config.py            # Settings da .env (DATABASE_URL, media, proxy, Telegram, impersonate)
│   ├── database.py          # layer DB su psycopg (pool + query-builder compat) + storage immagini
│   └── scheduler.py         # APScheduler: registra i 4 job ricorrenti
├── scrapers/
│   ├── base.py              # interfaccia ScrapedListing / BaseScraper (Strategy pattern)
│   ├── subito.py            # scraper Subito: curl_cffi/hades, parsing, pHash, split routing
│   └── nlp_parser.py        # pre-parsing regex: km/anno, storage/batteria, features, difetti
└── services/
    ├── reads.py             # query di lettura + orchestrazione BI (margini, valutazione, TTS)
    ├── scoring.py           # Deal Score, offerta suggerita, penalità difetti, radar riparazioni
    ├── valuation.py         # Fase 2: valore equo, posizione prezzo, affare-vs-truffa
    ├── variants.py          # Fase 1: resolver variante canonica + condition tier
    ├── notifications.py     # notifiche Telegram (opportunità, cali, alert di sistema)
    ├── health.py            # Fase 3: stato scraper (scrape_runs) + alert down/ripristino
    └── garbage_collector.py # decadimento annunci (schedulato) → alimenta il time-to-sale

database/
├── selfhosted/
│   ├── init.sql             # SCHEMA CONSOLIDATO (fa fede per installazioni nuove; auto su Docker)
│   └── align_from_supabase.sql  # allinea uno schema ripristinato da Supabase al codice
└── 01…15_*.sql              # storico delle migrazioni incrementali (evoluzione schema)

scripts/
├── api_explorer.py          # reverse engineering / debug dell'endpoint hades
├── run_backfill.py          # "aspirapolvere": scraping storico profondo per target
├── garbage_collector.py     # wrapper CLI del GC schedulato
├── dump_supabase.sh         # dump del vecchio DB Supabase (session pooler)
├── restore_db.sh            # ripristina un dump in qualunque Postgres (locale/VPS)
├── backup_db.sh             # pg_dump compresso periodico (cron sul VPS)
├── seed_target_models.py    # seed/upsert dei modelli da monitorare
├── test_intelligence.py     # test NLP (tech+auto) + scoring
├── test_variants.py         # test resolver varianti (Fase 1)
├── test_valuation.py        # test valutazione predittiva (Fase 2)
├── test_health.py           # test logica stato scraper (Fase 3)
└── test_db_shim.py          # test generazione SQL del layer DB

frontend/
└── src/
    ├── app/
    │   ├── page.tsx         # dashboard "FlipRadar" (Live Sniper / Market Intelligence / Pipeline / Automations)
    │   ├── scanner/page.tsx # vista legacy (mock, non collegata)
    │   └── calculator/page.tsx  # calcolatore margini standalone (legacy)
    ├── components/          # sidebar, grafico trend, calcolatore margine
    └── lib/
        ├── api.ts           # client fetch verso il backend (opportunità, trends, deals)
        └── flipradar-data.ts # formattazione EUR, colori margine/score/dealClass, tempo relativo
```

## Responsabilità dei moduli chiave

- **`tasks.py`** — orchestrazione dei motori (Sniper, Notturno), `persist_opportunities`
  (routing/dedup/UPSERT), IQR, hook notifiche e salute.
- **`services/reads.py`** — tutto ciò che alimenta il frontend: assembla per ogni
  opportunità margine, variante, valore equo, Deal Score, assistente di trattativa,
  time-to-sale e prezzi di rivendita.
- **`services/variants.py` / `valuation.py` / `scoring.py`** — il layer di Business
  Intelligence (vedi [DATA-INTELLIGENCE.md](DATA-INTELLIGENCE.md)), funzioni pure e testate.
- **`core/database.py`** — shim che replica l'API di `supabase-py` su un pool psycopg:
  i ~60 call site restano invariati; migrare Postgres = cambiare `DATABASE_URL`.
