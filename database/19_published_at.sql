-- =====================================================================
--  MIGRAZIONE 19 — published_at: quando l'annuncio è uscito su Subito
--  Target: PostgreSQL self-hosted (Docker)
--
--  found_at = quando NOI l'abbiamo visto. Per un annuncio recuperato da un
--  backfill (pubblicato giorni prima) found_at sottostima età e tempo di
--  vendita. published_at viene dall'API (dates.display_iso8601): le nuove
--  righe lo hanno subito, quelle vecchie lo ricevono quando lo Sniper le
--  rivede. Le letture usano coalesce(published_at, found_at).
--  Idempotente.
-- =====================================================================

alter table public.live_opportunities_tech add column if not exists published_at timestamptz;
alter table public.live_opportunities_auto add column if not exists published_at timestamptz;
