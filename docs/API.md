# API REST & script

## Endpoint

| Endpoint | Metodo | Descrizione |
|---|---|---|
| `/health` | GET | Liveness minimale |
| `/health/scraper` | GET | Salute raccolta: ultimo giro per categoria, proxy, pool impersonation |
| `/api/opportunities?category=smartphone\|automobile&limit=60` | GET | Feed arricchito: margine, valore equo, posizione, classe affare, Deal Score, assistente trattativa |
| `/api/opportunities/{id}?category=...` | PATCH | Aggiorna lo stato di un'opportunità (es. `visto`) |
| `/api/trends?category=...` | GET | KPI verticale: annunci attivi, prezzo medio, time-to-sale, serie storica, classifica per modello (liquidità + rivendita) |
| `/api/deals` | GET / POST | Pipeline P&L: lista / crea affare |
| `/api/deals/summary` | GET | KPI P&L: investito, profitto realizzato, margine reale medio |
| `/api/deals/{id}` | PATCH / DELETE | Aggiorna stato/prezzi/costi o elimina |
| `/api/scrape/test-subito?query=...&category=...&pages=...` | GET | Scraping manuale on-demand (debug) |
| `/api/scrape/run-nightly?query=...&category=...` | GET | Motore Notturno on-demand (debug) |

Doc automatica: `http://localhost:8000/docs`.

## Script operativi

| Script | Quando usarlo |
|---|---|
| `seed_target_models.py` | Bootstrap/aggiornamento della flotta di target |
| `run_backfill.py [max_pages] [category]` | Popolamento storico profondo di un target |
| `garbage_collector.py [category]` | Lancio manuale del GC (gira già ogni notte) |
| `dump_supabase.sh` / `restore_db.sh` / `backup_db.sh` | Migrazione dati e backup DB |
| `api_explorer.py "query"` | Debug/reverse engineering di `hades` |
| `test_intelligence.py` / `test_variants.py` / `test_valuation.py` / `test_health.py` / `test_db_shim.py` | Test delle funzioni pure (NLP, scoring, varianti, valutazione, salute, layer DB) |
| `test_sniper_auto.py` | Collaudo manuale split routing verticale auto |
