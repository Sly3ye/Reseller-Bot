-- =====================================================================
--  MIGRAZIONE 06 — Isolamento statistico per target_id
--  Target: Supabase (PostgreSQL 15+)
--  Ogni annuncio e ogni snapshot di mercato sono legati al target che li ha
--  generati, così la media/IQR si raggruppa in modo rigoroso per target_id:
--  una BMW 120d Gen 1 non inquina mai la media di una Gen 3.
--
--  ATTENZIONE: fa TRUNCATE dei dati di test incompatibili (annunci e trend)
--  per ripartire da un DB pulito, come richiesto.
-- =====================================================================

-- 0. Pulizia dati di test incompatibili (privi di target_id).
truncate table public.live_opportunities;
truncate table public.market_trends;

-- 1. Annunci → target_id (FK con cascade: eliminando un target si puliscono).
alter table public.live_opportunities
  add column if not exists target_id uuid
    references public.target_models (id) on delete cascade;

create index if not exists idx_opportunities_target
  on public.live_opportunities (target_id);

-- 2. Statistiche di mercato → target_id.
alter table public.market_trends
  add column if not exists target_id uuid
    references public.target_models (id) on delete cascade;

-- La chiave di unicità passa da (product_id, giorno) a (target_id, giorno):
-- uno snapshot per target al giorno, così l'IQR è isolato per target.
alter table public.market_trends
  drop constraint if exists uq_trends_product_date;

create unique index if not exists uq_trends_target_date
  on public.market_trends (target_id, trend_date);

create index if not exists idx_trends_target
  on public.market_trends (target_id, trend_date desc);

-- =====================================================================
-- FINE MIGRAZIONE 06
-- =====================================================================
