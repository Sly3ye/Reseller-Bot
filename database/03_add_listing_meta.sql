-- =====================================================================
--  MIGRAZIONE 03 — Metadati annuncio per la UI (feed Live Sniper)
--  Target: Supabase (PostgreSQL 15+)
--  Persistiamo titolo e località così la tabella del frontend mostra
--  dati reali senza doverli ricavare dallo slug dell'URL.
-- =====================================================================

alter table public.live_opportunities
  add column if not exists title    text,
  add column if not exists location text;

comment on column public.live_opportunities.title is
  'Titolo dell''annuncio come scrapato dalla pagina di ricerca.';
comment on column public.live_opportunities.location is
  'Località/città dell''annuncio, quando disponibile.';

-- =====================================================================
-- FINE MIGRAZIONE 03
-- =====================================================================
