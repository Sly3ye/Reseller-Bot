-- =====================================================================
--  MIGRAZIONE 15 — Colonne variante tech (NLP smartphone)
--  Target: Supabase (PostgreSQL 15+)
--
--  Il parser NLP ora estrae anche il segnale tech: taglio di memoria,
--  salute batteria, difetti (schermo rotto, iCloud bloccato...) e flag di
--  urgenza. Le istanze fresche le hanno già dalla migrazione 12; questa
--  ALTER allinea le istanze live pre-esistenti. Idempotente.
-- =====================================================================

alter table public.live_opportunities_tech
  add column if not exists storage_gb    integer,
  add column if not exists battery_pct   integer,
  add column if not exists defects_noted jsonb,
  add column if not exists urgency_flags jsonb;

-- Segmentazione di mercato per variante: lookup veloce per taglio memoria.
create index if not exists idx_tech_storage
  on public.live_opportunities_tech (storage_gb);

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 15
-- =====================================================================
