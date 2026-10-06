# Unire il DB del secondo PC nel principale (da fare sul Mac)

Guida operativa per **Claude sul Mac** (o per te a mano). Unisce il dump raccolto
sull'altro PC (vedi [RACCOLTA-SU-QUESTO-PC.md](RACCOLTA-SU-QUESTO-PC.md)) dentro il
DB principale, **senza perdere né sovrascrivere** nulla.

## Perché è sicuro
- Tutte le chiavi primarie sono **UUID** → due istanze non generano ID in
  collisione.
- I target si allineano per **identità** `(category, query, strict_filters)`,
  non per UUID: lo script rimappa `target_id` da solo. Un target senza filtri
  (es. "BMW 123d" generico) ripiega sul target **attivo** con lo stesso nome.
  Stessa chiave su tutte le macchine dalla migrazione 29.
- Il merge è **additivo, idempotente e atomico**: porta solo ciò che manca,
  rilanciarlo non duplica, e in caso di errore fa rollback (principale intatto).

## Cosa fa lo script `scripts/merge_instances.py`
- **target_models**: mappa per identità (vedi sopra, `scripts/target_identity.py`);
  i target presenti solo nel PC vengono aggiunti (stesso UUID).
- **live_opportunities_tech / _auto**: inserisce solo gli annunci **nuovi**, dedup
  su `listing_url` (quelli già nel principale non si toccano). `target_id`
  rimappato.
- **price_history**: porta lo storico dei soli annunci inseriti (niente orfani).
- **NON** tocca gli annunci esistenti, **NON** unisce `market_trends` (aggregato
  ricalcolabile), ignora `sent_alerts` e `deals` (stato locale).

## Passi
```bash
# 0. Aggiorna il codice E applica le migrazioni PRIMA del merge.
#    Lo script copia solo le colonne presenti in ENTRAMBI i DB: se il Mac non
#    ha le migrazioni 18–22 (published_at, raw_image_urls, estimate/repair...)
#    quei campi del PC si perdono in silenzio. Il backend le applica da solo
#    all'avvio.
git pull
docker compose up -d --build
docker compose exec -T db psql -U postgres -d reseller -tc "select max(version) from schema_migrations"   # → 22_target_fk_set_null

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

# 7. Riconoscimento aggiornato anche sulle righe già presenti sul Mac (memoria,
#    modello dalla descrizione, guasti v2): il merge non le tocca.
docker compose exec -T backend python scripts/backfill_model_storage.py --apply
docker compose exec -T backend python scripts/reparse_nlp.py --apply
```

> **Passaggio del 2026-10-02 (PC → Mac).** L'inventario sul PC non ha fatto
> in tempo a finire: nel dump nessun annuncio è marcato venduto (giusto: si
> marca solo con un giro completo). Il primo inventario completo girerà sul
> Mac, subito, grazie al recupero automatico (l'ultimo ha più di 26h). Le foto
> dell'archivio ancora da scaricare restano in coda (`raw_image_urls`): sul Mac
> il job `photo_backfill` continua da solo, finché Subito le tiene online.
> Sul Mac poi: password del DB non di default (RACCOLTA-SU-QUESTO-PC.md,
> sezione Sicurezza).
> Sostituisci `PWD` con `POSTGRES_PASSWORD` e `reseller_pc_AAAA-MM-GG.dump` col
> nome reale del file scaricato da Drive. Se il Postgres principale **non** è in
> Docker, salta i `docker compose exec` e usa `pg_dump/pg_restore/psql` diretti
> verso `localhost:5432`.

> **Merge eseguito il 2026-10-03 sul Mac** (dump del 2026-10-02): +44.860
> annunci tech (6.934 → 51.794), +36 auto, +198 righe di storico, +17 target
> (iPhone 8–12 e 18). Foto **non ancora** importate (passo 6 da fare quando
> arriva l'archivio). Cosa è emerso:
> - **Seed saltato**: sul Mac il vincolo è `unique (category, query,
>   strict_filters)` (target BMW per generazione), non `(category, query)`;
>   `seed_targets.py` va in errore. Non serviva: la flotta del Mac era già
>   allineata (gen 13–17 + 2 BMW attivi).
> - Lo script ora inserisce i target con `on conflict do nothing` e, a parità
>   di nome, mappa sul target **attivo** (sul Mac "BMW 125i" esiste per due
>   generazioni).
> - 225 annunci tech + 3 auto avevano lo stesso id sui due DB ma `listing_url`
>   diverso (portati dal merge di luglio, poi aggiornati a una ripubblicazione
>   su una sola macchina): sono già nel principale, ora vengono saltati anche
>   per id invece di far fallire tutto il merge.

## Passaggio del 2026-10-05 sera (PC → Mac, tutto sul Mac)

Il 2026-10-05 il **PC** ha raccolto fino alle 17:45 (iPhone + tutte le auto:
inventario, venduti, foto, dati strutturati delle auto, dalle 12:50 anche
testa della coda e ricontrollo degli affari); il Mac era fermo dal merge del
2026-10-03. Il merge normale PC → Mac **non basta**: aggiunge solo gli
annunci nuovi e perderebbe venduti, ribassi, foto e dati auto registrati sul
PC per annunci già presenti sul Mac. Si fa al contrario, tutto sul Mac.

**Novità di compose (Goal Version P0):** due servizi con la stessa immagine.
`backend` = solo dashboard e API (scheduler sempre spento, si ricostruisce
quando vuoi senza fermare la raccolta); `collector` = raccolta (sweep, testa
della coda, inventari, foto, alert, bot Telegram), nessuna porta esposta. La
pagina Automazioni dell'API inoltra i comandi al `collector`.

```bash
git pull
# 0. .env di root del Mac: SCHEDULER_ENABLED assente o true (ora vale solo per
#    il collector), AUTO_FULL_CATEGORY=true (scelta del 5/10, vedi sotto),
#    nessuna riga COLLECTOR_URL (il default http://collector:8000 è giusto).
# 1. Backup del DB attuale del Mac (diventerà la SORGENTE del merge)
docker compose exec -T db pg_dump -U postgres -d reseller -Fc > backup_mac_$(date +%F).dump
# 2. Il vecchio DB del Mac in un DB temporaneo
docker compose exec -T db createdb -U postgres reseller_mac
docker compose exec -T db pg_restore -U postgres --no-owner -d reseller_mac < backup_mac_AAAA-MM-GG.dump
# 3. Il dump del PC DIVENTA il principale (sostituisce reseller). Prima si
#    ferma tutto ciò che scrive nel DB.
docker compose stop backend collector
docker compose exec -T db dropdb -U postgres reseller
docker compose exec -T db createdb -U postgres reseller
docker compose exec -T db pg_restore -U postgres --no-owner -d reseller < reseller_pc_2026-10-05.dump
docker compose up -d --build backend          # applica le migrazioni mancanti; NON raccoglie
# 4. Merge vecchio Mac → nuovo principale: entrano gli annunci che aveva solo il Mac
docker compose exec -T backend sh -c 'SOURCE_DATABASE_URL=${DATABASE_URL%/reseller}/reseller_mac TARGET_DATABASE_URL=$DATABASE_URL python scripts/merge_instances.py --dry-run'
docker compose exec -T backend sh -c 'SOURCE_DATABASE_URL=${DATABASE_URL%/reseller}/reseller_mac TARGET_DATABASE_URL=$DATABASE_URL python scripts/merge_instances.py --yes'
docker compose exec -T db dropdb -U postgres reseller_mac
# 5. Foto (passo 6 sopra) e ricalcoli
docker compose exec -T backend sh -c "mkdir -p /data/media && tar xzf - -C /data/media" < media_pc_2026-10-05.tar.gz
docker compose exec -T backend python scripts/backfill_car_variants.py --apply
# 6. Solo adesso la raccolta (e il backup notturno)
docker compose up -d --build collector backup
docker compose logs -f collector              # "Scheduler started with jobs: [...]", poi "Testa smartphone: +N nuovi"
```

Lo stato del ciclo d'inventario auto viaggia nel dump (`app_settings`): il
Mac lo continua. Dopo un'ora, in **Qualità del dato** compaiono le richieste
di oggi per lavoro (`testa`, `sweep`, `inventario`, `ricontrollo_affari`…):
è il budget reale dallo stesso IP.

**Telegram:**
1. `TELEGRAM_BOT_TOKEN` in `backend/.env` (mai in chat né nel repository),
   poi `docker compose up -d backend collector`.
2. In **Impostazioni → Chat Telegram** scrivi gli ID delle chat e premi **Salva**.
3. Premi **Prova iPhone**, **Prova auto** e **Prova sistema**. Arriva un alert
   vero con foto, offerta da copiare e bottoni; se non arriva, accanto al
   pulsante compare l'errore esatto di Telegram (chat sbagliata, bot non
   avviato…).
4. Premi un bottone sotto l'alert (es. ⭐ Salva): l'annuncio deve comparire in
   pipeline entro 30 secondi. Questo vuol dire che il bot del collector riceve
   i comandi.

Gli alert auto partono solo se imposti almeno un criterio del compratore
(marca, zona, raggio o budget).

**Tutte le auto sullo stesso IP (`AUTO_FULL_CATEGORY=true`).** La Goal Version
(§4) consiglia di spegnerle sul nodo degli iPhone: la testa delle auto costa
1.440 richieste al giorno e la fetta notturna ~1.400. Resta accesa per scelta
del 5/10; il segnale per spegnerla (`AUTO_FULL_CATEGORY=false` nel `.env`,
poi `docker compose up -d collector`) è la riga "Richieste oggi" con blocchi,
o pause del governatore nei log (`Governatore: … in pausa`).

Deciso il 5/10: si tiene tutto acceso. **Se arrivano blocchi**, si passa alla
via di mezzo: solo gli annunci nuovi delle auto (testa e sweep, circa 1.700
richieste al giorno), senza l'inventario a rotazione.
Basta una riga nel `.env` di root del Mac:
`SCHEDULER_SKIP=inventory_auto,inventory_watchdog_auto`, poi
`docker compose up -d collector`. I modelli di prezzo delle auto continuano
a crescere; i venduti delle auto no, finché l'amico non usa il programma.

**Ambito iPhone dal 12 in su (5/10).** I modelli più vecchi, gli accessori e
gli altri marchi già raccolti sono nella tabella
`live_opportunities_tech_archivio`, che viaggia nel dump: sul Mac non c'è
niente da fare. Per rimetterli al loro posto:
`docker compose exec -T backend python scripts/archive_out_of_scope.py --restore`.

**Verifiche dei venduti a metà.** L'inventario iPhone del 5/10 ha trovato
~3.600 candidati venduti. La loro coda (`verify_queue:smartphone` in
`app_settings`) viaggia nel dump e il `collector` del Mac la riprende da solo
entro 30 minuti. I venduti già verificati sul PC sono già marcati. In
**Qualità del dato** la riga "possibili venduti da verificare" scende.

**Sul PC, dopo il dump.** Dalle 14:02 del 5/10 raccoglie il `collector` di
compose, avviato con `SCHEDULER_ENABLED=true` da riga di comando: il `.env` di
root dice `false`. I container fatti a mano sono fermi. Da qui in poi il PC
serve solo come dashboard.

```bash
docker compose stop collector
docker rm boh-collector boh-photos boh-head      # i vecchi container fatti a mano, già fermi
docker compose up -d backend
```

Sul Mac non servono né `SCHEDULER_SKIP` né `SCHEDULER_ONLY`: girano tutti i
lavori, compresa la fetta auto, che sul PC il pomeriggio del 5/10 era spenta
per dare la precedenza alle verifiche dei venduti iPhone.

> **Eseguito il 2026-10-06 notte sul Mac** (dump PC del 5/10 come principale,
> vecchio Mac dentro). Il Mac aveva raccolto dal 3 al 5/10 (54.776 iPhone).
> Esito: iPhone 38.078 → 43.415 (+5.337 visti solo dal Mac), auto 78.093 →
> 81.718 (+3.625, storico BMW del Mac), +1.219 righe di storico prezzi, +173
> target (BMW per generazione, quasi tutti spenti). Poi `seed_targets.py`
> (29 iPhone dal 12 + 2 BMW per generazione), `archive_out_of_scope.py --apply`
> (122 fuori ambito arrivati dal Mac), backfill memoria/modello, reparse NLP,
> varianti auto, foto del PC (8,7 GB). Differenze dalla procedura:
> - il vecchio DB del Mac **non** è stato cancellato: `alter database reseller
>   rename to reseller_mac` (è già la sorgente del passo 2), poi `createdb` +
>   `pg_restore` del dump PC. Si elimina a mano quando il nuovo principale è
>   verificato;
> - il merge ora **salta gli annunci già nell'archivio fuori ambito** del
>   principale (`<tabella>_archivio`, migrazione 28): senza, 11.450 iPhone
>   archiviati sul PC tornavano nella tabella viva.

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
> allineano per identità e gli annunci gen 17 finiscono sui target
> giusti invece di crearne di nuovi. Attenzione: il seed **spegne** ogni target
> attivo fuori dalla sua lista (es. gli iPhone sotto `IPHONE_MIN_GEN`).

## Note sull'allineamento dei target
- Gli **iPhone** combaciano al 100% (query deterministiche, filtri vuoti).
- Le **auto** hanno un target per generazione (fasce d'anno in `strict_filters`;
  i BMW attivi sono 123d 2007–2013 e 125i 2012–2019, da `seed_targets.py`).
  Un target con nome diverso o con filtri diversi da tutti quelli del principale
  arriva come target nuovo (nessun annuncio perso). Per fonderlo, allinea
  `query`/`strict_filters` in `target_models` e rilancia il merge (idempotente).
