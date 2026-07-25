-- =====================================================================
--  MIGRAZIONE 12 — Baseline tabelle live_opportunities_auto / _tech
--  Target: Supabase (PostgreSQL 15+)
--
--  Le due tabelle primarie erano state create a mano sull'istanza live e
--  non erano versionate: un deploy pulito era impossibile. Questo file le
--  crea da zero (idempotente) con TUTTE le colonne usate dal codice, così
--  lo schema è riproducibile su un progetto Supabase vergine.
--
--  Su un'istanza già esistente "create table if not exists" non fa nulla:
--  le colonne mancanti sono coperte dalle ALTER in coda (idempotenti).
-- =====================================================================

-- ------------------------------------------------------------ AUTO
create table if not exists public.live_opportunities_auto (
  id             uuid primary key default gen_random_uuid(),
  target_id      uuid references public.target_models (id) on delete cascade,
  listing_url    text not null,
  title          text,
  description    text,
  location       text,
  asking_price   numeric(12,2) not null,
  original_price numeric(12,2),
  image_urls     jsonb not null default '[]'::jsonb,
  status         public.opportunity_status not null default 'nuovo',
  found_at       timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- dedup / intelligence
  image_hash     text,
  features       jsonb,
  seller_id      text,
  seller_type    text,
  -- campi strutturati auto
  year           integer,
  km             integer,
  transmission   text,
  fuel           text,
  defects_noted  jsonb,
  urgency_flags  jsonb,

  constraint uq_opportunities_auto_url unique (listing_url)
);

comment on table public.live_opportunities_auto is
  'Opportunità del verticale auto trovate dal Cecchino (table-per-type).';

-- ------------------------------------------------------------ TECH
create table if not exists public.live_opportunities_tech (
  id             uuid primary key default gen_random_uuid(),
  target_id      uuid references public.target_models (id) on delete cascade,
  listing_url    text not null,
  title          text,
  description    text,
  location       text,
  asking_price   numeric(12,2) not null,
  original_price numeric(12,2),
  image_urls     jsonb not null default '[]'::jsonb,
  status         public.opportunity_status not null default 'nuovo',
  found_at       timestamptz not null default now(),
  updated_at     timestamptz not null default now(),
  -- dedup / intelligence
  image_hash     text,
  features       jsonb,
  seller_id      text,
  seller_type    text,
  -- variante tech (NLP: migrazione 15 per le istanze live)
  storage_gb     integer,
  battery_pct    integer,
  defects_noted  jsonb,
  urgency_flags  jsonb,

  constraint uq_opportunities_tech_url unique (listing_url)
);

comment on table public.live_opportunities_tech is
  'Opportunità del verticale tech/smartphone trovate dal Cecchino (table-per-type).';

-- ------------------------------------------------- colonne su istanze live
-- (no-op sulle installazioni fresche; allineano le istanze pre-esistenti)
alter table public.live_opportunities_auto
  add column if not exists seller_type text;
alter table public.live_opportunities_tech
  add column if not exists seller_type text;

-- ------------------------------------------------------------ indici
create index if not exists idx_auto_status_found
  on public.live_opportunities_auto (status, found_at desc);
create index if not exists idx_tech_status_found
  on public.live_opportunities_tech (status, found_at desc);

create index if not exists idx_auto_target
  on public.live_opportunities_auto (target_id);
create index if not exists idx_tech_target
  on public.live_opportunities_tech (target_id);

create index if not exists idx_auto_image_hash
  on public.live_opportunities_auto (image_hash);
create index if not exists idx_tech_image_hash
  on public.live_opportunities_tech (image_hash);

create index if not exists idx_auto_seller
  on public.live_opportunities_auto (seller_id);
create index if not exists idx_tech_seller
  on public.live_opportunities_tech (seller_id);

-- ------------------------------------------------------------ RLS
alter table public.live_opportunities_auto enable row level security;
alter table public.live_opportunities_tech enable row level security;

drop policy if exists "opportunities_auto_read_authenticated"
  on public.live_opportunities_auto;
create policy "opportunities_auto_read_authenticated"
  on public.live_opportunities_auto for select
  to authenticated
  using ( true );

drop policy if exists "opportunities_tech_read_authenticated"
  on public.live_opportunities_tech;
create policy "opportunities_tech_read_authenticated"
  on public.live_opportunities_tech for select
  to authenticated
  using ( true );

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 12
-- =====================================================================
