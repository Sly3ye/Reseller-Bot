-- =====================================================================
--  MIGRAZIONE 10 — features (NLP normalizzato) + seller_id (Shadow Dealer)
--  Target: Supabase (PostgreSQL 15+)
--
--  - features:   allestimenti/optional normalizzati dal parser NLP (JSONB).
--  - seller_id:  id venditore da Subito (advertiser.user_id). Serve a contare
--                gli annunci attivi per venditore e smascherare i "finti privati"
--                (privati con > 3 annunci attivi in _auto → finto_privato).
--  Idempotente.
-- =====================================================================

alter table public.live_opportunities_auto
  add column if not exists features jsonb,
  add column if not exists seller_id text;

alter table public.live_opportunities_tech
  add column if not exists features jsonb,
  add column if not exists seller_id text;

-- Conteggio rapido degli annunci attivi per venditore (Shadow Dealer).
create index if not exists idx_auto_seller
  on public.live_opportunities_auto (seller_id);

create index if not exists idx_tech_seller
  on public.live_opportunities_tech (seller_id);

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 10
-- =====================================================================
