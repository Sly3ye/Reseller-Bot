-- =====================================================================
--  SCHEMA SQL — SaaS Arbitraggio (iPhone usati + Auto usate)
--  Target: Supabase (PostgreSQL 15+)
--  Pronto da incollare nell'SQL Editor di Supabase.
-- =====================================================================

-- ---------------------------------------------------------------------
-- 0. ESTENSIONI
-- ---------------------------------------------------------------------
create extension if not exists "pgcrypto"; -- per gen_random_uuid()

-- ---------------------------------------------------------------------
-- 1. ENUM TYPES
-- ---------------------------------------------------------------------
-- Categoria merceologica del prodotto tracciato
create type public.product_category as enum ('smartphone', 'auto');

-- Ciclo di vita di un'opportunità trovata dal Motore Cecchino
create type public.opportunity_status as enum ('nuovo', 'visto', 'scaduto');

-- ---------------------------------------------------------------------
-- 2. FUNZIONE TRIGGER: aggiornamento automatico di updated_at
-- ---------------------------------------------------------------------
create or replace function public.handle_updated_at()
returns trigger
language plpgsql
as $$
begin
  new.updated_at = now();
  return new;
end;
$$;

-- ---------------------------------------------------------------------
-- 3. TABELLA: profiles
--    Estensione 1:1 di auth.users (il PK è anche FK verso auth.users)
-- ---------------------------------------------------------------------
create table public.profiles (
  id            uuid primary key references auth.users (id) on delete cascade,
  full_name     text,
  role          text not null default 'reseller',          -- es. 'reseller', 'admin'
  subscribed_at timestamptz not null default now(),        -- data iscrizione
  created_at    timestamptz not null default now(),
  updated_at    timestamptz not null default now()
);

comment on table public.profiles is 'Dati del reseller, estensione della tabella auth.users di Supabase.';

create trigger trg_profiles_updated_at
  before update on public.profiles
  for each row execute function public.handle_updated_at();

-- (Consigliato) Trigger che crea automaticamente il profilo alla registrazione
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer set search_path = public
as $$
begin
  insert into public.profiles (id, full_name)
  values (new.id, new.raw_user_meta_data ->> 'full_name');
  return new;
end;
$$;

create trigger trg_on_auth_user_created
  after insert on auth.users
  for each row execute function public.handle_new_user();

-- ---------------------------------------------------------------------
-- 4. TABELLA: products
--    Catalogo dei modelli tracciati (smartphone e auto).
--    Le specifiche variabili vivono in "specs" (JSONB):
--      iPhone -> {"storage_gb": 128, "color": "Graphite"}
--      Auto   -> {"engine": "2.0 TDI", "year": 2018, "fuel": "diesel"}
-- ---------------------------------------------------------------------
create table public.products (
  id         uuid primary key default gen_random_uuid(),
  category   public.product_category not null,
  brand      text not null,                    -- es. 'Apple', 'Volkswagen'
  model      text not null,                    -- es. 'iPhone 13 Pro', 'Golf'
  specs      jsonb not null default '{}'::jsonb, -- specifiche flessibili
  is_active  boolean not null default true,    -- flag per i motori di scraping
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),

  -- Evita duplicati esatti dello stesso modello + specifiche
  constraint uq_products_identity unique (category, brand, model, specs)
);

comment on table public.products is 'Catalogo dei modelli tracciati dai motori di scraping.';
comment on column public.products.specs is 'Specifiche variabili in JSONB (storage, colore, motore, anno, ecc.).';

create trigger trg_products_updated_at
  before update on public.products
  for each row execute function public.handle_updated_at();

-- Indici: ricerca per categoria e query dentro il JSONB
create index idx_products_category on public.products (category);
create index idx_products_specs_gin on public.products using gin (specs);

-- ---------------------------------------------------------------------
-- 5. TABELLA: market_trends
--    Popolata dal MOTORE NOTTURNO (batch). Uno snapshot per prodotto/giorno.
-- ---------------------------------------------------------------------
create table public.market_trends (
  id          uuid primary key default gen_random_uuid(),
  product_id  uuid not null references public.products (id) on delete cascade,
  trend_date  date not null,                       -- giorno dello snapshot
  avg_price   numeric(12,2) not null,              -- prezzo medio di mercato
  min_price   numeric(12,2) not null,
  max_price   numeric(12,2) not null,
  volume      integer not null default 0,          -- n. annunci analizzati
  created_at  timestamptz not null default now(),
  updated_at  timestamptz not null default now(),

  -- Un solo snapshot per prodotto per giorno (il batch può fare UPSERT)
  constraint uq_trends_product_date unique (product_id, trend_date),
  constraint chk_trends_prices check (min_price <= avg_price and avg_price <= max_price)
);

comment on table public.market_trends is 'Storico prezzi giornaliero calcolato dal Motore Notturno (alimenta i grafici).';

create trigger trg_market_trends_updated_at
  before update on public.market_trends
  for each row execute function public.handle_updated_at();

-- Indice ottimizzato per i grafici: serie temporale per prodotto
create index idx_trends_product_date on public.market_trends (product_id, trend_date desc);

-- ---------------------------------------------------------------------
-- 6. TABELLA: live_opportunities
--    Popolata dal MOTORE CECCHINO (ogni 15 min). Annunci sottoprezzati.
-- ---------------------------------------------------------------------
create table public.live_opportunities (
  id               uuid primary key default gen_random_uuid(),
  product_id       uuid not null references public.products (id) on delete cascade,
  listing_url      text not null,                          -- link all'annuncio
  asking_price     numeric(12,2) not null,                 -- prezzo richiesto dal venditore
  market_avg_price numeric(12,2),                          -- media di mercato al momento del rilevamento
  estimated_margin numeric(12,2),                          -- margine stimato (market_avg - asking)
  margin_pct       numeric(5,2),                           -- margine in % (comodo per ordinare/filtrare)
  status           public.opportunity_status not null default 'nuovo',
  source           text,                                   -- es. 'subito', 'autoscout24'
  found_at         timestamptz not null default now(),     -- quando il cecchino l'ha trovato
  created_at       timestamptz not null default now(),
  updated_at       timestamptz not null default now(),

  -- Lo stesso annuncio non viene inserito due volte
  constraint uq_opportunities_url unique (listing_url)
);

comment on table public.live_opportunities is 'Opportunità di arbitraggio trovate dal Motore Cecchino (ogni 15 minuti).';

create trigger trg_live_opportunities_updated_at
  before update on public.live_opportunities
  for each row execute function public.handle_updated_at();

-- Indici: feed "nuove opportunità" e lookup per prodotto
create index idx_opportunities_status_found on public.live_opportunities (status, found_at desc);
create index idx_opportunities_product on public.live_opportunities (product_id);

-- ---------------------------------------------------------------------
-- 7. ROW LEVEL SECURITY (RLS)
--    Nota: i motori di scraping devono scrivere usando la SERVICE ROLE KEY
--    (che bypassa la RLS), quindi non servono policy di INSERT/UPDATE
--    per i client sulle tabelle dati.
-- ---------------------------------------------------------------------
alter table public.profiles           enable row level security;
alter table public.products           enable row level security;
alter table public.market_trends      enable row level security;
alter table public.live_opportunities enable row level security;

-- PROFILES: ogni utente vede e modifica SOLO il proprio profilo
create policy "profiles_select_own"
  on public.profiles for select
  to authenticated
  using ( auth.uid() = id );

create policy "profiles_update_own"
  on public.profiles for update
  to authenticated
  using ( auth.uid() = id )
  with check ( auth.uid() = id );

-- PRODUCTS: lettura per tutti gli utenti autenticati
create policy "products_read_authenticated"
  on public.products for select
  to authenticated
  using ( true );

-- MARKET_TRENDS: lettura per tutti gli utenti autenticati
create policy "trends_read_authenticated"
  on public.market_trends for select
  to authenticated
  using ( true );

-- LIVE_OPPORTUNITIES: lettura per tutti gli utenti autenticati
create policy "opportunities_read_authenticated"
  on public.live_opportunities for select
  to authenticated
  using ( true );

-- =====================================================================
-- FINE SCHEMA
-- =====================================================================
