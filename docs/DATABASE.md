# Modello dati

Lo schema completo e riproducibile vive in **`database/selfhosted/init.sql`**
(applicato automaticamente da Docker al primo avvio del volume). Postgres puro
(enum, JSONB, trigger, indici GIN) — nessuna dipendenza da Supabase, RLS/Auth
rimosse perché l'unico client che si connette è il backend, fidato.

| Tabella | Scopo |
|---|---|
| `target_models` | **Flotta di scraping dinamica**: ogni riga è un modello da monitorare (query + `strict_filters` JSONB: anno/km/cambio auto, memoria/batteria tech). Aggiungere un target = una `INSERT`. Unicità su `(category, query, strict_filters)` → più generazioni dello stesso modello auto convivono. |
| `products` | Catalogo dei modelli tracciati (brand, categoria, specs). |
| `live_opportunities_auto` / `live_opportunities_tech` | **Table-per-type**: annunci trovati dal Cecchino, separati per verticale. Colonne comuni + specifiche (auto: anno/km/cambio/carburante; tech: `storage_gb`/`battery_pct`) + segnale NLP (`features`, `defects_noted`, `urgency_flags`), venditore (`seller_id`/`seller_type`), `image_hash` (pHash), e **Fase 1**: `variant_key` + `condition_tier`. |
| `market_trends` | Snapshot giornaliero media/min/max/volume prezzi, isolato per `target_id`. |
| `price_history` | Storico dei cali di prezzo per annuncio (alimenta il Price Drop Alert). |
| `sent_alerts` | Dedup notifiche Telegram: vincolo `(listing_id, alert_type)`. |
| `deals` | **Pipeline P&L**: affari seguiti (ciclo di vita, prezzi/costi reali → profitto netto). |
| `scrape_runs` | **Fase 3**: un record per giro dello Sniper (stato ok/degraded/down) per il monitoraggio salute. |
| `/media` (filesystem) | Gallerie fotografiche riscaricate (i link Subito scadono), servite da FastAPI su `/media/...`. |

## Enum

- `product_category`: `smartphone` · `auto` · `automobile`
- `opportunity_status`: `nuovo` · `visto` · `scaduto` · `venduto_rimosso`

## Note

- **Installazione nuova** → fa fede `selfhosted/init.sql`. I file `01…15_*.sql`
  sono lo **storico** dell'evoluzione (erano le migrazioni incrementali
  dell'istanza Supabase).
- **`align_from_supabase.sql`** allinea uno schema *ripristinato da Supabase*
  (più vecchio) al codice: aggiunge le colonne variante/tech, converte array
  `text[]`→`jsonb`, crea `sent_alerts`/`deals`/`scrape_runs`. Idempotente.
- Non esiste ancora un **migration runner** versionato per aggiornamenti
  incrementali di uno schema già popolato (vedi [ROADMAP.md](ROADMAP.md)).
