-- =====================================================================
--  MIGRAZIONE 18 — scrape_runs: costo e copertura di ogni giro
--  Target: PostgreSQL self-hosted (Docker)
--
--  Senza proxy (dal 2026-10-02) si scrapa da un solo IP a ritmo controllato.
--  Per regolare la cadenza sui numeri servono due misure per giro:
--  - requests: chiamate a Subito fatte (il costo del giro);
--  - gaps: target che non si sono ricongiunti con la scansione precedente
--    entro il tetto di pagine → annunci persi, cadenza troppo lenta.
--  Idempotente.
-- =====================================================================

alter table public.scrape_runs add column if not exists requests integer;
alter table public.scrape_runs add column if not exists gaps integer;
