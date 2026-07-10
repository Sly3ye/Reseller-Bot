-- =====================================================================
--  MIGRAZIONE 09 — image_hash (Perceptual Hash anti-ripubblicazione)
--  Target: Supabase (PostgreSQL 15+)
--
--  I venditori cancellano e ripubblicano lo stesso annuncio per sembrare
--  "nuovi". Salviamo il pHash della prima foto: se ricompare sotto un nuovo
--  listing_url, riconosciamo la ripubblicazione e aggiorniamo il record
--  esistente invece di duplicarlo. Idempotente.
-- =====================================================================

alter table public.live_opportunities_auto
  add column if not exists image_hash text;

alter table public.live_opportunities_tech
  add column if not exists image_hash text;

-- Lookup veloce del pHash in fase di UPSERT (dedup anti-ripubblicazione).
create index if not exists idx_auto_image_hash
  on public.live_opportunities_auto (image_hash);

create index if not exists idx_tech_image_hash
  on public.live_opportunities_tech (image_hash);

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 09
-- =====================================================================
