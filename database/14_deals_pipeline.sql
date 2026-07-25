-- =====================================================================
--  MIGRAZIONE 14 — Tabella deals (pipeline P&L compra-rivendi)
--  Target: Supabase (PostgreSQL 15+)
--
--  Il gestionale dell'impresa: ogni affare seguito vive qui con il suo
--  ciclo di vita (interessante → contattato → offerta → comprato →
--  in_vendita → venduto | sfumato), i costi accessori e il profitto reale.
--  Chiude il feedback loop: dopo N affari si confronta il margine stimato
--  dal bot con quello effettivamente incassato. Idempotente.
-- =====================================================================

create table if not exists public.deals (
  id           uuid primary key default gen_random_uuid(),
  listing_id   uuid,                        -- opportunità di origine (se dal feed)
  category     text not null,               -- 'smartphone' | 'automobile'
  title        text,
  listing_url  text,
  stage        text not null default 'interessante',
  -- economics
  asking_price numeric(12,2),               -- prezzo richiesto al momento dell'aggancio
  market_avg   numeric(12,2),               -- media di mercato snapshot (stima margine)
  offer_price  numeric(12,2),               -- offerta fatta al venditore
  buy_price    numeric(12,2),               -- prezzo effettivamente pagato
  extra_costs  jsonb not null default '[]'::jsonb,  -- [{"label":"batteria","amount":79}]
  sell_price   numeric(12,2),               -- prezzo di rivendita incassato
  notes        text,
  created_at   timestamptz not null default now(),
  updated_at   timestamptz not null default now(),

  constraint chk_deals_stage check (
    stage in ('interessante','contattato','offerta','comprato',
              'in_vendita','venduto','sfumato')
  )
);

comment on table public.deals is
  'Pipeline P&L: ciclo di vita degli affari seguiti, dal feed alla rivendita.';

drop trigger if exists trg_deals_updated_at on public.deals;
create trigger trg_deals_updated_at
  before update on public.deals
  for each row execute function public.handle_updated_at();

create index if not exists idx_deals_stage
  on public.deals (stage, updated_at desc);
create index if not exists idx_deals_listing
  on public.deals (listing_id);

alter table public.deals enable row level security;

drop policy if exists "deals_read_authenticated" on public.deals;
create policy "deals_read_authenticated"
  on public.deals for select
  to authenticated
  using ( true );

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 14
-- =====================================================================
