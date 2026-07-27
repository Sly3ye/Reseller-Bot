# Setup, configurazione & deploy

## Prerequisiti
- **Docker + Docker Compose** (modo consigliato: Postgres + backend con un comando)
- Node.js 18+ (solo per il frontend)
- (Opzionale, consigliato) credenziali proxy residenziale rotante + bot Telegram

## 1. Avvio con Docker (consigliato)

```bash
cp .env.example .env                  # POSTGRES_PASSWORD (+ PUBLIC_MEDIA_BASE_URL in prod)
cp backend/.env.example backend/.env  # proxy IPRoyal + Telegram (facoltativi)

docker compose up -d                  # avvia Postgres + backend
docker compose logs -f backend        # segui lo Sniper
```

Al primo avvio Postgres esegue `database/selfhosted/init.sql` (schema + target
pilota). API su `http://localhost:8000` (`/docs`), immagini su `/media/...`.

Sul **VPS**: identico — installa Docker, clona, imposta `PUBLIC_MEDIA_BASE_URL`
col dominio/IP pubblico in `.env`, `docker compose up -d`.

## 1-bis. Avvio senza Docker (sviluppo)

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
createdb reseller && psql -d reseller -f database/selfhosted/init.sql
cp backend/.env.example backend/.env
export DATABASE_URL="postgresql://postgres:postgres@localhost:5432/reseller"
uvicorn backend.main:app --reload --port 8000
```

## 2. Frontend

```bash
cd frontend && npm install && npm run dev   # http://localhost:3000
```
Override backend con `NEXT_PUBLIC_API_BASE_URL`.

## 3. Target, backfill, notifiche, GC, backup, test

```bash
python scripts/seed_target_models.py        # popola/aggiorna la flotta pilota
python scripts/seed_iphone_targets.py        # gamma iPhone COMPLETA (31 modelli)
python scripts/run_backfill.py 10           # aspirapolvere: 10 pagine/target
python scripts/garbage_collector.py          # GC on-demand (gira già ogni notte)
./scripts/backup_db.sh                        # pg_dump compresso in ./backups (cron sul VPS)
python scripts/test_intelligence.py          # test NLP + scoring
python scripts/test_variants.py              # test resolver varianti
python scripts/test_valuation.py             # test valutazione
python scripts/test_health.py                # test stato scraper
```

**Telegram**: crea un bot con @BotFather, metti `TELEGRAM_BOT_TOKEN` + i chat ID
in `backend/.env`.

## Configurazione (.env)

`backend/.env` per i segreti dell'app; `.env` (root) per docker-compose.

| Variabile | Dove | Descrizione |
|---|---|---|
| `DATABASE_URL` | backend | Connessione Postgres. Con Docker la imposta il compose. |
| `MEDIA_ROOT` | backend | Cartella immagini (default `./media`; Docker `/data/media`) |
| `PUBLIC_MEDIA_BASE_URL` | backend/root | URL pubblico da cui il browser carica le immagini |
| `POSTGRES_PASSWORD` | root | Password Postgres in container |
| `PROXY_HOST/PORT/USER/PASS` | backend | Proxy residenziale per `hades`; se vuoti → diretta |
| `SCRAPER_IMPERSONATE` | backend | Pool impronte curl_cffi, virgola (default `safari,firefox`) |
| `TELEGRAM_BOT_TOKEN` | backend | Token bot; vuoto → notifiche off |
| `TELEGRAM_CHAT_ID_TECH/AUTO/OPS` | backend | Chat per verticali e alert di sistema |
| `ALERT_MIN_MARGIN_PCT` / `ALERT_MIN_DROP_PCT` | backend | Soglie alert (default 20 / 10) |
| `CORS_ORIGINS` | backend | Origini frontend ammesse |

## Backup, pausa & ripristino

- **DB** → `scripts/backup_db.sh` (pg_dump). Ripristino in qualunque Postgres:
  `scripts/restore_db.sh <dump> <DATABASE_URL>`.
- **Immagini** → stanno in `/media` (volume Docker `media`): per un backup
  completo salva sia il dump SQL sia il volume.
- **Mettere in pausa un VPS senza perdere dati** = snapshot del server **e/o**
  `pg_dump` scaricato in locale, poi eliminare il server. Spegnere soltanto NON
  ferma la fatturazione cloud.

## Note di design / limiti noti

- La dashboard reale è `frontend/src/app/page.tsx`; `scanner`/`calculator` sono
  viste legacy su dati mock, non collegate.
- Il pannello **Automations** è ancora dimostrativo (Force Run/intervallo non
  pilotano davvero lo scheduler) → Fase 5.
- Lo scheduler gira **in-process**: in produzione un solo worker, altrimenti
  ogni worker duplica i job.
- I **costi di riparazione/penalità** in `scoring.py` sono euristiche da tarare
  con la Pipeline P&L.
- Migrazioni: `init.sql` per installazioni nuove; manca un runner versionato per
  aggiornamenti incrementali (vedi [ROADMAP.md](ROADMAP.md)).
