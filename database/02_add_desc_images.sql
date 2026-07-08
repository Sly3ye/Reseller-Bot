-- =====================================================================
--  MIGRAZIONE 02 — Deep Scraping: descrizione e immagini persistite
--  Target: Supabase (PostgreSQL 15+)
--  Aggiunge a live_opportunities i campi per il dataset Computer Vision.
-- =====================================================================

alter table public.live_opportunities
  add column if not exists description text,
  add column if not exists image_urls  jsonb not null default '[]'::jsonb;

comment on column public.live_opportunities.description is
  'Testo della descrizione dell''annuncio (stato d''uso, accessori, ecc.).';
comment on column public.live_opportunities.image_urls is
  'Lista di URL pubblici (bucket Supabase listing_images) delle immagini scaricate. '
  'Non usiamo i link originali di Subito perché scadono.';

-- =====================================================================
-- FINE MIGRAZIONE 02
-- =====================================================================
