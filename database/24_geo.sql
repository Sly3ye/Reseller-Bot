-- =====================================================================
--  MIGRAZIONE 24 — posizione dell'annuncio (comune con coordinate)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Subito dà per ogni annuncio comune (con lat/lon), provincia e regione.
--  Servono a ordinare per distanza da casa (un'auto lontana costa mezza
--  giornata per andarla a vedere) e agli alert per raggio. Idempotente.
-- =====================================================================

alter table public.live_opportunities_tech add column if not exists geo_lat double precision;
alter table public.live_opportunities_tech add column if not exists geo_lon double precision;
alter table public.live_opportunities_tech add column if not exists province text;
alter table public.live_opportunities_tech add column if not exists region text;
alter table public.live_opportunities_auto add column if not exists geo_lat double precision;
alter table public.live_opportunities_auto add column if not exists geo_lon double precision;
alter table public.live_opportunities_auto add column if not exists province text;
alter table public.live_opportunities_auto add column if not exists region text;
