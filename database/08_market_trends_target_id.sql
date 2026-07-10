-- =====================================================================
--  MIGRAZIONE 08 — target_id su market_trends (isolamento statistico)
--  Target: Supabase (PostgreSQL 15+)
--
--  La tabella live market_trends risultava priva della colonna target_id
--  (la ALTER della migrazione 06 non era stata applicata a questa tabella),
--  perciò il Motore Notturno ripiegava sull'upsert per (product_id, giorno).
--  Con più target che condividono la stessa query (es. BMW 120i Gen1/Gen2/Gen3
--  con range anni diversi) il product_id collide: questa migrazione ripristina
--  l'isolamento per target. Idempotente.
-- =====================================================================

alter table public.market_trends
  add column if not exists target_id uuid
    references public.target_models (id) on delete cascade;

-- Uno snapshot per target al giorno → l'IQR resta isolato per generazione.
create unique index if not exists uq_trends_target_date
  on public.market_trends (target_id, trend_date);

create index if not exists idx_trends_target
  on public.market_trends (target_id, trend_date desc);

-- Ricarica la cache dello schema così PostgREST vede subito la colonna.
notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 08
-- =====================================================================
