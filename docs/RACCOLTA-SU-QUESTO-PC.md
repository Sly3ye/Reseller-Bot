# Raccogliere dati da questo PC (istanza secondaria)

Obiettivo: accendere il backend qui, con un DB **da zero**, e accumulare annunci
in parallelo al Mac. I dati saranno **uniti** al DB principale più avanti
(vedi [MERGE-DB.md](MERGE-DB.md)). Nessun dato va perso: gli ID sono UUID e i
target si allineano per nome `(category, query)`.

> **Un solo scraper alla volta è più pulito**, ma non obbligatorio: anche se sia
> Mac che PC raccolgono, il merge deduplica gli annunci su `listing_url`.

## Prerequisiti
- **Docker Desktop** attivo.
- Nessun proxy: lo scraper va in diretta su `hades.subito.it` a ritmo
  controllato (vedi [ARCHITETTURA.md](ARCHITETTURA.md#ritmo-da-un-solo-ip-niente-proxy)).
  ⚠️ Se Mac e PC scrapano **dalla stessa rete di casa** escono con lo stesso IP
  e si dividono lo stesso limite: meglio uno solo alla volta.
- (Opzionale) **Ollama** in esecuzione sull'host per l'analisi AI locale.

## Avvio (una volta)
```bash
# 1. Config del compose (password Postgres)
cp .env.example .env
#    → apri .env e imposta POSTGRES_PASSWORD

# 2. Segreti dell'app (Telegram, opzionale)
cp backend/.env.example backend/.env
#    → lascia vuoti i PROXY_*. Telegram puoi lasciarlo vuoto: qui stai solo
#      accumulando.

# 3. Su lo stack: Postgres (schema da init.sql al 1° avvio) + backend + scheduler
docker compose up -d --build

# 4. Imposta la flotta ESATTA: iPhone 13→16 (+16e) e BMW 123d/125i,
#    e spegne i target pilota (Golf GTI ecc.)
docker compose exec backend python scripts/seed_targets.py
```

Fatto. Lo **scheduler parte da solo**: il cecchino tech gira ogni ~15 minuti, quello
auto ogni ~30. Da qui in poi il DB si riempie.

## Verifica che stia raccogliendo
- Log backend: `docker compose logs -f backend` → cerca `Scheduler started with jobs`
  e i giri sniper.
- API viva: apri <http://localhost:8000> (health) e `GET /api/opportunities`.
- (Opzionale) frontend per guardarli:
  ```bash
  cd frontend && npm install && npm run dev   # → http://localhost:3000
  ```
  Il pannello **Automations** mostra salute scraper e copertura; **Tempo di
  vendita** e **Market Intelligence** matureranno con i dati.

## Sicurezza: password del DB
Le porte di DB (5432) e API (8000) ascoltano solo su `127.0.0.1`: dalla rete
non si raggiungono. La password del DB va comunque cambiata da quella di
default (`postgres`), in due passi, **con lo stesso valore**:

```powershell
# 1. Cambia la password nel DB (la chiede due volte, non resta nella cronologia)
docker compose exec db psql -U postgres -d reseller -c "\password postgres"
# 2. Scrivi lo stesso valore in .env alla riga POSTGRES_PASSWORD=..., poi
docker compose up -d backend backup
```

`POSTGRES_PASSWORD` nel `.env` vale solo per creare il DB la prima volta:
per questo serve il passo 1. Il `.env` è git-ignorato: la password non va
mai in un commit né in chat.

## Backup automatici
Il servizio `backup` del compose (parte con `docker compose up -d`) ogni notte
alle 5:00, o appena il PC si riaccende se l'ultimo ha più di 26 ore:
- dump in `backups/db/` (14 giorni), **verificato** ripristinandolo in un DB
  di prova;
- copia speculare delle foto in `backups/media/` (solo le nuove);
- esito nel cruscotto **Qualità del dato** e allarme Telegram (chat ops) alle
  10:00 se è fallito o più vecchio di 36 ore.

Un giro subito: `docker compose run --rm -e BACKUP_NOW=1 backup`.
Sono una protezione per **questa** macchina (disco che si rompe, volume
cancellato): non sostituiscono il passaggio dei dati al Mac qui sotto.

## Quando hai finito di lavorare qui
1. **Dump del DB** del PC (formato custom, compresso). In `backups/`, che è
   git-ignorata: un dump non va mai committato.
   ```bash
   mkdir -p backups
   docker compose exec -T db pg_dump -U postgres -d reseller -Fc \
     > backups/reseller_pc_$(date +%F).dump
   ```
2. **Archivio delle immagini.** Le foto NON stanno nel DB: sono file sul volume
   `media`, e le righe le referenziano per percorso. Senza questo archivio, dopo
   il merge il Mac mostra il feed **senza foto** (galleria e lightbox vuote) per
   tutti gli annunci importati.
   ```bash
   docker compose exec -T backend sh -c "cd /data/media && tar czf - ." \
     > backups/media_pc_$(date +%F).tar.gz
   ```
3. Carica **entrambi** i file su **Google Drive**.
4. `git push` di tutto il codice (incluso questo repo aggiornato).
5. Sul Mac: segui [MERGE-DB.md](MERGE-DB.md) per unire dump e immagini.

> Il dump è una **fotografia**: se dopo averlo fatto lo scheduler continua a
> raccogliere, quegli annunci non ci sono. Rifallo come ultima cosa prima di
> spegnere (rilanciare il merge non duplica nulla, è idempotente).

> **Regola d'oro:** il DB del Mac è la base. Al merge si *aggiunge* ad esso; non
> si ripristina mai il dump del PC *sopra* il principale.
