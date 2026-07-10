-- =====================================================================
--  MIGRAZIONE 05 — Tabella target_models (flotta di scraping dinamica)
--  Target: Supabase (PostgreSQL 15+)
--  I modelli da monitorare (auto e smartphone) vivono nel DB, non più
--  hardcoded: aggiungere un target = inserire una riga qui.
-- =====================================================================

create table if not exists public.target_models (
  id             uuid primary key default gen_random_uuid(),
  category       text not null,                         -- 'automobile', 'smartphone', ...
  query          text not null,                         -- termine di ricerca su Subito
  strict_filters jsonb not null default '{}'::jsonb,    -- anno/km/memoria/cambio ecc.
  is_active      boolean not null default true,
  last_scanned   timestamptz,                           -- ultimo giro dello sniper
  created_at     timestamptz not null default now(),

  constraint uq_target_models_identity unique (category, query)
);

comment on table public.target_models is
  'Flotta dinamica di target di scraping letta dallo Sniper (is_active = true).';
comment on column public.target_models.strict_filters is
  'Filtri flessibili applicati in-blocco (es. {"min_year":2017,"max_km":100000}).';

alter table public.target_models enable row level security;

create policy "target_models_read_authenticated"
  on public.target_models for select
  to authenticated
  using ( true );

-- ---------------------------------------------------------------------
-- Seed dati pilota (idempotente)
-- ---------------------------------------------------------------------
insert into public.target_models (category, query, strict_filters, is_active)
values
  (
    'automobile',
    'Golf GTI',
    '{"min_year": 2017, "max_year": 2020, "max_km": 100000, "transmission": "automatic"}'::jsonb,
    true
  ),
  (
    'smartphone',
    'iPhone 14',
    '{}'::jsonb,
    true
  )
on conflict (category, query) do nothing;

-- =====================================================================
-- FINE MIGRAZIONE 05
-- =====================================================================
