-- =====================================================================
--  SCHEMA CONSOLIDATO — Reseller Bot self-hosted (PostgreSQL 15+)
--
--  Schema completo e riproducibile per un Postgres TUO (Docker in locale o
--  sul VPS). Racchiude in un unico file lo stato finale delle migrazioni
--  01→15, SENZA le parti specifiche di Supabase che l'app non usa:
--  niente schema `auth`, niente tabella `profiles`, niente RLS/policy
--  (l'unico client che si connette è il backend, fidato).
--
--  Docker esegue automaticamente questo file al primo avvio del volume
--  (montato in /docker-entrypoint-initdb.d/). Idempotente: "if not exists"
--  ovunque, così rilanciarlo non rompe nulla.
-- =====================================================================

create extension if not exists "pgcrypto";  -- gen_random_uuid()

-- ---------------------------------------------------------------- enums
do $$ begin
  create type public.product_category as enum ('smartphone', 'auto', 'automobile');
exception when duplicate_object then null; end $$;

do $$ begin
  create type public.opportunity_status as enum
    ('nuovo', 'visto', 'scaduto', 'venduto_rimosso');
exception when duplicate_object then null; end $$;

-- ------------------------------------------------- trigger updated_at
create or replace function public.handle_updated_at()
returns trigger language plpgsql as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------- products
create table if not exists public.products (
  id         uuid primary key default gen_random_uuid(),
  category   public.product_category not null,
  brand      text not null,
  model      text not null,
  specs      jsonb not null default '{}'::jsonb,
  is_active  boolean not null default true,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  constraint uq_products_identity unique (category, brand, model, specs)
);
create index if not exists idx_products_category on public.products (category);
create index if not exists idx_products_specs_gin on public.products using gin (specs);

drop trigger if exists trg_products_updated_at on public.products;
create trigger trg_products_updated_at
  before update on public.products
  for each row execute function public.handle_updated_at();

-- ---------------------------------------------------------- target_models
create table if not exists public.target_models (
  id             uuid primary key default gen_random_uuid(),
  category       text not null,
  query          text not null,
  strict_filters jsonb not null default '{}'::jsonb,
  is_active      boolean not null default true,
  last_scanned   timestamptz,
  created_at     timestamptz not null default now(),
  constraint uq_target_models_identity unique (category, query)
);

-- ---------------------------------------------------------- market_trends
create table if not exists public.market_trends (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references public.products (id) on delete cascade,
  target_id   uuid references public.target_models (id) on delete cascade,
  trend_date  date not null,
  avg_price   numeric(12,2) not null,
  min_price   numeric(12,2) not null,
  max_price   numeric(12,2) not null,
  volume      integer not null default 0,
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),
  constraint chk_trends_prices check (min_price <= avg_price and avg_price <= max_price)
);
create unique index if not exists uq_trends_target_date
  on public.market_trends (target_id, trend_date);
create index if not exists idx_trends_target
  on public.market_trends (target_id, trend_date desc);
create index if not exists idx_trends_product_date
  on public.market_trends (product_id, trend_date desc);

drop trigger if exists trg_market_trends_updated_at on public.market_trends;
create trigger trg_market_trends_updated_at
  before update on public.market_trends
  for each row execute function public.handle_updated_at();

-- ------------------------------------------------ live_opportunities_auto
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
  image_hash     text,
  features       jsonb,
  seller_id      text,
  seller_type    text,
  year           integer,
  km             integer,
  transmission   text,
  fuel           text,
  defects_noted  jsonb,
  urgency_flags  jsonb,
  variant_key    text,
  condition_tier text,
  constraint uq_opportunities_auto_url unique (listing_url)
);
create index if not exists idx_auto_status_found on public.live_opportunities_auto (status, found_at desc);
create index if not exists idx_auto_target      on public.live_opportunities_auto (target_id);
create index if not exists idx_auto_image_hash  on public.live_opportunities_auto (image_hash);
create index if not exists idx_auto_seller      on public.live_opportunities_auto (seller_id);
create index if not exists idx_auto_variant     on public.live_opportunities_auto (variant_key);
alter table public.live_opportunities_auto add column if not exists color text;
alter table public.live_opportunities_auto add column if not exists triage text;
create index if not exists idx_auto_triage      on public.live_opportunities_auto (triage);

-- ------------------------------------------------ live_opportunities_tech
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
  image_hash     text,
  features       jsonb,
  seller_id      text,
  seller_type    text,
  storage_gb     integer,
  battery_pct    integer,
  color          text,
  defects_noted  jsonb,
  urgency_flags  jsonb,
  variant_key    text,
  condition_tier text,
  ai_analysis    jsonb,
  constraint uq_opportunities_tech_url unique (listing_url)
);
create index if not exists idx_tech_status_found on public.live_opportunities_tech (status, found_at desc);
create index if not exists idx_tech_target      on public.live_opportunities_tech (target_id);
create index if not exists idx_tech_image_hash  on public.live_opportunities_tech (image_hash);
create index if not exists idx_tech_seller      on public.live_opportunities_tech (seller_id);
create index if not exists idx_tech_storage     on public.live_opportunities_tech (storage_gb);
create index if not exists idx_tech_variant     on public.live_opportunities_tech (variant_key);
alter table public.live_opportunities_tech add column if not exists triage text;
create index if not exists idx_tech_triage      on public.live_opportunities_tech (triage);

-- ---------------------------------------------------------- price_history
create table if not exists public.price_history (
  id         uuid primary key,
  listing_id uuid not null,
  old_price  numeric not null,
  new_price  numeric not null,
  changed_at timestamptz default now()
);
create index if not exists idx_price_history_listing
  on public.price_history (listing_id, changed_at desc);

-- ------------------------------------------------------------ scrape_runs
create table if not exists public.scrape_runs (
  id         uuid primary key default gen_random_uuid(),
  category   text,
  status     text,
  targets    integer,
  ok         integer,
  failed     integer,
  scraped    integer,
  new_count  integer,
  ran_at     timestamptz not null default now()
);
create index if not exists idx_scrape_runs_cat on public.scrape_runs (category, ran_at desc);

-- ------------------------------------------------------------ sent_alerts
create table if not exists public.sent_alerts (
  id          uuid primary key default gen_random_uuid(),
  listing_id  uuid not null,
  alert_type  text not null,
  category    text,
  margin_pct  numeric(6,1),
  sent_at     timestamptz not null default now(),
  constraint uq_sent_alerts_listing_type unique (listing_id, alert_type)
);
create index if not exists idx_sent_alerts_sent on public.sent_alerts (sent_at desc);

-- ------------------------------------------------------------------ deals
create table if not exists public.deals (
  id           uuid primary key default gen_random_uuid(),
  listing_id   uuid,
  category     text not null,
  title        text,
  listing_url  text,
  stage        text not null default 'interessante',
  asking_price numeric(12,2),
  market_avg   numeric(12,2),
  offer_price  numeric(12,2),
  buy_price    numeric(12,2),
  extra_costs  jsonb not null default '[]'::jsonb,
  sell_price   numeric(12,2),
  notes        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),
  constraint chk_deals_stage check (
    stage in ('interessante','contattato','offerta','comprato',
              'in_vendita','venduto','sfumato')
  )
);
create index if not exists idx_deals_stage   on public.deals (stage, updated_at desc);
create index if not exists idx_deals_listing on public.deals (listing_id);

drop trigger if exists trg_deals_updated_at on public.deals;
create trigger trg_deals_updated_at
  before update on public.deals
  for each row execute function public.handle_updated_at();

-- ---------------------------------------------- seed target pilota (idempotente)
insert into public.target_models (category, query, strict_filters, is_active)
values
  ('automobile', 'Golf GTI',
   '{"min_year": 2017, "max_year": 2020, "max_km": 100000, "transmission": "automatic"}'::jsonb,
   true),
  ('smartphone', 'iPhone 14', '{}'::jsonb, true)
on conflict (category, query) do nothing;

-- =====================================================================
-- FINE SCHEMA CONSOLIDATO
-- =====================================================================
