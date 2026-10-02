-- =====================================================================
--  MIGRAZIONE 21 — URL originali delle foto (CDN Subito)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Le righe salvate senza scaricare le foto (inventario, deep sweep) perdevano
--  le URL della galleria. Ora si salvano sempre: il job photo_backfill le
--  scarica con calma dalla CDN delle immagini (host diverso da hades, non
--  consuma il budget di richieste anti-blocco). Idempotente.
-- =====================================================================

alter table public.live_opportunities_tech add column if not exists raw_image_urls jsonb;
alter table public.live_opportunities_auto add column if not exists raw_image_urls jsonb;

-- Coda del backfill: righe con galleria nota ma foto non ancora scaricate.
create index if not exists idx_tech_photo_queue on public.live_opportunities_tech (found_at desc)
  where image_urls = '[]'::jsonb and raw_image_urls is not null;
