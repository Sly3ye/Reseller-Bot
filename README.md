# FlipRadar — Reseller Arbitrage Bot

Sistema automatico di **arbitraggio su annunci di seconda mano** (iPhone e auto)
che monitora Subito.it 24/7, calcola il **valore equo di ogni annuncio**, segnala
in tempo reale (anche su Telegram) le occasioni sottoprezzate distinguendo gli
affari veri dalle truffe, e accompagna l'intero ciclo compra-rivendi in una
**pipeline P&L**.

Nato come strumento operativo per **due attività reali**: rivendita di iPhone
usati (verticale *tech*) e di auto usate (verticale *auto*), con statistiche e
margini isolati per verticale e per variante.

| Componente | Ruolo | Stack |
|---|---|---|
| **Backend** (`backend/`) | Scraping, NLP, Business Intelligence, notifiche, API | Python 3.11+, FastAPI, curl_cffi, APScheduler, psycopg |
| **Frontend** (`frontend/`) | Dashboard (Live Sniper, Market Intelligence, Pipeline P&L) | Next.js 16, React 19, TypeScript |
| **Database** (`database/`) | Schema consolidato + immagini su filesystem | **PostgreSQL self-hosted** (Docker) |

> **Self-hosted, zero abbonamenti.** Girava su Supabase; migrato a PostgreSQL
> self-hosted + immagini su disco, così gira sul tuo hardware (mini PC o VPS)
> senza limiti né canoni. Tutto parte con `docker compose up`.

## Come funziona (in breve)

Subito.it è una SPA che carica gli annunci da un'API JSON interna
(`hades.subito.it`), individuata per reverse engineering: la interroghiamo
direttamente (con **curl_cffi** per superare l'anti-bot Akamai, via **proxy
residenziale**), senza browser headless. Uno **scheduler** interno lancia i
"cecchini" (ogni 5' tech, 15' auto) che raccolgono gli annunci, li parsano
(NLP), li deduplicano (pHash) e li salvano in Postgres. In lettura, un layer di
**Business Intelligence** assegna a ogni annuncio la sua **variante canonica**,
ne stima il **valore equo**, calcola margine, **Deal Score** e posizione di
mercato, e distingue **affare / caro / sospetto**. Le occasioni migliori
arrivano su **Telegram** e nella **dashboard**; gli affari seguiti finiscono
nella **pipeline P&L** con profitto netto reale.

## Avvio rapido

```bash
cp .env.example .env                  # POSTGRES_PASSWORD (+ PUBLIC_MEDIA_BASE_URL in prod)
cp backend/.env.example backend/.env  # proxy IPRoyal + Telegram (facoltativi)
docker compose up -d                  # Postgres + backend (Sniper attivo)
docker compose logs -f backend        # segui la raccolta

cd frontend && npm install && npm run dev   # dashboard su http://localhost:3000
```

API su `http://localhost:8000` (`/docs`). Dettagli, config e deploy →
[docs/DEPLOY.md](docs/DEPLOY.md).

## Documentazione

| Documento | Contenuto |
|---|---|
| [docs/ARCHITETTURA.md](docs/ARCHITETTURA.md) | Architettura, anti-Akamai, split routing, flusso end-to-end, stack |
| [docs/STRUTTURA-CODICE.md](docs/STRUTTURA-CODICE.md) | Albero del codice e responsabilità dei moduli |
| [docs/FEATURES.md](docs/FEATURES.md) | Feature di raccolta e operatività |
| [docs/DATA-INTELLIGENCE.md](docs/DATA-INTELLIGENCE.md) | Il layer BI: varianti, valutazione, Deal Score, time-to-sale, pipeline |
| [docs/DATABASE.md](docs/DATABASE.md) | Modello dati e migrazioni |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Setup, configurazione `.env`, backup, deploy, limiti noti |
| [docs/API.md](docs/API.md) | Endpoint REST e script operativi |
| [docs/VISIONE-IPHONE.md](docs/VISIONE-IPHONE.md) | Definizione di "fatto" per il verticale iPhone: schermate, analitiche, funzionalità |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Cosa manca / da implementare (backlog prioritizzato) |
