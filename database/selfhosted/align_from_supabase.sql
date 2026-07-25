-- =====================================================================
--  ALLINEAMENTO — schema ripristinato da Supabase → schema del codice
--  (PostgreSQL 15+). One-time, idempotente.
--
--  I dati veri vengono dal dump Supabase, ma quell'istanza non aveva le
--  migrazioni recenti: mancano le colonne variante/NLP del tech, gli array
--  erano text[] dove il codice usa jsonb, e le tabelle sent_alerts/deals
--  (notifiche + pipeline P&L) non esistevano. Questo file colma il divario.
--
--  Da rilanciare in sicurezza quante volte serve.
-- =====================================================================

-- 1. AUTO: converti gli array text[] → jsonb (to_jsonb preserva i valori
--    come array JSON di stringhe, esattamente come li rilegge il codice).
do $$
begin
  if (select udt_name from information_schema.columns
      where table_name = 'live_opportunities_auto'
        and column_name = 'defects_noted') = '_text' then
    alter table public.live_opportunities_auto
      alter column defects_noted type jsonb using to_jsonb(defects_noted);
  end if;
  if (select udt_name from information_schema.columns
      where table_name = 'live_opportunities_auto'
        and column_name = 'urgency_flags') = '_text' then
    alter table public.live_opportunities_auto
      alter column urgency_flags type jsonb using to_jsonb(urgency_flags);
  end if;
end $$;

-- 2. TECH: colonne variante (segmentazione) + segnale NLP mancanti.
alter table public.live_opportunities_tech
  add column if not exists storage_gb    integer,
  add column if not exists battery_pct   integer,
  add column if not exists defects_noted jsonb,
  add column if not exists urgency_flags jsonb;
create index if not exists idx_tech_storage
  on public.live_opportunities_tech (storage_gb);

-- 2b. Varianti canoniche (Fase 1 BI): scrematura pulita per (modello,memoria)
--     tech e (modello,generazione) auto + fascia di condizione.
alter table public.live_opportunities_auto
  add column if not exists variant_key    text,
  add column if not exists condition_tier text;
alter table public.live_opportunities_tech
  add column if not exists variant_key    text,
  add column if not exists condition_tier text;
create index if not exists idx_auto_variant on public.live_opportunities_auto (variant_key);
create index if not exists idx_tech_variant on public.live_opportunities_tech (variant_key);
alter table public.live_opportunities_auto add column if not exists color text;
alter table public.live_opportunities_tech add column if not exists color text;
create index if not exists idx_tech_color on public.live_opportunities_tech (color);
-- AI locale (Ollama): analisi semantica delle descrizioni.
alter table public.live_opportunities_tech add column if not exists ai_analysis jsonb;
alter table public.live_opportunities_auto add column if not exists ai_analysis jsonb;

-- 2c. scrape_runs (Fase 3): salute dello scraper, un record per giro Sniper.
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

-- 3. sent_alerts (dedup notifiche Telegram) — migrazione 13.
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

-- 4. deals (pipeline P&L) — migrazione 14.
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

-- =====================================================================
-- FINE ALLINEAMENTO
-- =====================================================================
