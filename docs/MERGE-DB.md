# Unire il DB del secondo PC nel principale (da fare sul Mac)

Guida operativa per **Claude sul Mac** (o per te a mano). Unisce il dump raccolto
sull'altro PC (vedi [RACCOLTA-SU-QUESTO-PC.md](RACCOLTA-SU-QUESTO-PC.md)) dentro il
DB principale, **senza perdere né sovrascrivere** nulla.

## Perché è sicuro
- Tutte le chiavi primarie sono **UUID** → due istanze non generano ID in
  collisione.
- I target si allineano per **nome** `(category, query)`, non per UUID: lo script
  rimappa `target_id` da solo. iPhone e BMW sono stati seedati con le stesse query
  su entrambe le macchine (`scripts/seed_targets.py`), quindi combaciano.
- Il merge è **additivo, idempotente e atomico**: porta solo ciò che manca,
  rilanciarlo non duplica, e in caso di errore fa rollback (principale intatto).

## Cosa fa lo script `scripts/merge_instances.py`
- **target_models**: mappa per `(category, query)`; i target presenti solo nel PC
  vengono aggiunti (stesso UUID).
- **live_opportunities_tech / _auto**: inserisce solo gli annunci **nuovi**, dedup
  su `listing_url` (quelli già nel principale non si toccano). `target_id`
  rimappato.
- **price_history**: porta lo storico dei soli annunci inseriti (niente orfani).
- **NON** tocca gli annunci esistenti, **NON** unisce `market_trends` (aggregato
  ricalcolabile), ignora `sent_alerts` e `deals` (stato locale).

## Passi
```bash
# 0. Aggiorna il codice (per avere lo script)
git pull

# 1. BACKUP del principale (sempre, prima di scrivere)
#    Se il principale gira in Docker come l'altro PC:
docker compose exec -T db pg_dump -U postgres -d reseller -Fc \
  > backup_principale_$(date +%F).dump

# 2. Ripristina il dump del PC in un DB TEMPORANEO separato (non il principale!)
docker compose exec -T db createdb -U postgres reseller_pc
docker compose exec -T db pg_restore -U postgres -d reseller_pc < reseller_pc_AAAA-MM-GG.dump

# 3. ANTEPRIMA del merge (non scrive niente): conta cosa entrerebbe
docker compose exec -T backend env \
  SOURCE_DATABASE_URL=postgresql://postgres:PWD@db:5432/reseller_pc \
  TARGET_DATABASE_URL=postgresql://postgres:PWD@db:5432/reseller \
  python scripts/merge_instances.py --dry-run

# 4. APPLICA il merge
docker compose exec -T backend env \
  SOURCE_DATABASE_URL=postgresql://postgres:PWD@db:5432/reseller_pc \
  TARGET_DATABASE_URL=postgresql://postgres:PWD@db:5432/reseller \
  python scripts/merge_instances.py --yes

# 5. Pulizia del DB temporaneo
docker compose exec -T db dropdb -U postgres reseller_pc

# 6. IMMAGINI: le foto non stanno nel DB (sono file sul volume `media`, le righe
#    le referenziano per percorso). Senza questo passo gli annunci importati
#    compaiono nel feed SENZA foto. È additivo: i file sono nominati per ID
#    annuncio, quindi non collidono con quelli già presenti sul Mac.
docker compose exec -T backend sh -c "mkdir -p /data/media && tar xzf - -C /data/media" \
  < media_pc_AAAA-MM-GG.tar.gz
```
> Sostituisci `PWD` con `POSTGRES_PASSWORD` e `reseller_pc_AAAA-MM-GG.dump` col
> nome reale del file scaricato da Drive. Se il Postgres principale **non** è in
> Docker, salta i `docker compose exec` e usa `pg_dump/pg_restore/psql` diretti
> verso `localhost:5432`.

## Dopo il merge
- **Rigenera gli aggregati**: attendi il batch notturno sul principale, oppure
  forzalo — `market_trends` (curve/momentum) si ricostruisce dai nuovi annunci.
- **Verifica in UI**: Market Intelligence, Tempo di vendita e il feed devono
  mostrare più volume/venduti, **con le foto** (se mancano, è saltato il passo 6).

### Contenuto del dump del 2026-07-28 (per verificare il merge)

| Tabella | Righe nel dump |
|---|---|
| `live_opportunities_tech` | 1.645 |
| `live_opportunities_auto` | 66 |
| `target_models` | 25 (22 iPhone attivi + 2 BMW + 1 pilota spento) |
| `price_history` | 8 |
| `scrape_runs` | 72 |
| `market_trends` | 0 — il batch notturno non aveva ancora girato qui |
| `deals`, `products` | 0 |

Immagini: **4.609 file**, ~416 MB scompattati.

Dopo il merge, sul principale gli annunci tech devono essere *almeno* la somma
dei due (meno i `listing_url` già presenti, che sono deduplicati di proposito).

> ⚠️ **La gamma iPhone è cambiata**: la flotta include ora la generazione 17
> (17, 17 Air, 17 Pro, 17 Pro Max, 17e). Prima del merge, sul Mac rilancia
> `python scripts/seed_targets.py` (dopo il `git pull`): così i target si
> allineano per `(category, query)` e gli annunci gen 17 finiscono sui target
> giusti invece di crearne di nuovi.

## Note sull'allineamento dei target
- Gli **iPhone** combaciano al 100% (query deterministiche da `seed_targets.py`).
- Per le **auto** (BMW 123d/125i): se sul Mac le query erano scritte diversamente
  (es. "BMW Serie 1 123d"), quei target non matchano per nome. Non è un problema:
  lo script li porta comunque come target nuovi (nessun annuncio perso). Se vuoi
  fonderli, rinomina la `query` in `target_models` così coincide, poi rilancia il
  merge (è idempotente).
