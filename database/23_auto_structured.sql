-- =====================================================================
--  MIGRAZIONE 23 — auto: dati strutturati di Subito (tutte le auto)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Subito dà per ogni auto marca / modello CON generazione / versione
--  (es. BMW · Serie 1 (E87) · 123d cat 5 porte Eletta DPF), potenza,
--  carrozzeria, porte, immatricolazione, classe emissioni. Con questi la
--  variante (marca-modello@generazione) e il valore equo valgono per
--  qualunque auto, senza tabelle scritte a mano. Idempotente.
-- =====================================================================

alter table public.live_opportunities_auto add column if not exists car_brand text;
alter table public.live_opportunities_auto add column if not exists car_model text;
alter table public.live_opportunities_auto add column if not exists car_version text;
alter table public.live_opportunities_auto add column if not exists power_kw integer;
alter table public.live_opportunities_auto add column if not exists body_type text;
alter table public.live_opportunities_auto add column if not exists doors text;
alter table public.live_opportunities_auto add column if not exists register_month integer;
alter table public.live_opportunities_auto add column if not exists emission_class text;

create index if not exists idx_auto_brand_model on public.live_opportunities_auto (car_brand, car_model);
