# Raccogliere dati da questo PC (istanza secondaria)

Obiettivo: accendere il backend qui, con un DB **da zero**, e accumulare annunci
in parallelo al Mac. I dati saranno **uniti** al DB principale più avanti
(vedi [MERGE-DB.md](MERGE-DB.md)). Nessun dato va perso: gli ID sono UUID e i
target si allineano per nome `(category, query)`.

> **Un solo scraper alla volta è più pulito**, ma non obbligatorio: anche se sia
> Mac che PC raccolgono, il merge deduplica gli annunci su `listing_url`.

## Prerequisiti
- **Docker Desktop** attivo.
- (Consigliato) credenziali **proxy IPRoyal** — le stesse usate sul Mac. Senza
  proxy lo scraper va in diretta su `hades.subito.it` e rischia blocchi Akamai.
- (Opzionale) **Ollama** in esecuzione sull'host per l'analisi AI locale.

## Avvio (una volta)
```bash
# 1. Config del compose (password Postgres)
cp .env.example .env
#    → apri .env e imposta POSTGRES_PASSWORD

# 2. Segreti dell'app (proxy + Telegram, opzionali ma il proxy è consigliato)
cp backend/.env.example backend/.env
#    → in backend/.env compila PROXY_HOST/PORT/USER/PASS (le tue IPRoyal)
#      Telegram puoi lasciarlo vuoto: qui stai solo accumulando.

# 3. Su lo stack: Postgres (schema da init.sql al 1° avvio) + backend + scheduler
docker compose up -d --build

# 4. Imposta la flotta ESATTA: iPhone 13→16 (+16e) e BMW 123d/125i,
#    e spegne i target pilota (Golf GTI ecc.)
docker compose exec backend python scripts/seed_targets.py
```

Fatto. Lo **scheduler parte da solo**: il cecchino tech gira ogni ~5 minuti, quello
auto ogni ~15. Da qui in poi il DB si riempie.

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

## Quando hai finito di lavorare qui
1. **Dump del DB** del PC (formato custom, compresso):
   ```bash
   docker compose exec -T db pg_dump -U postgres -d reseller -Fc \
     > reseller_pc_$(date +%F).dump
   ```
2. Carica `reseller_pc_*.dump` su **Google Drive**.
3. `git push` di tutto il codice (incluso questo repo aggiornato).
4. Sul Mac: segui [MERGE-DB.md](MERGE-DB.md) per unire il dump al DB principale.

> **Regola d'oro:** il DB del Mac è la base. Al merge si *aggiunge* ad esso; non
> si ripristina mai il dump del PC *sopra* il principale.
