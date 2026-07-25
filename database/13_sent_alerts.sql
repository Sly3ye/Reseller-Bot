-- =====================================================================
--  MIGRAZIONE 13 — Tabella sent_alerts (dedup notifiche Telegram)
--  Target: Supabase (PostgreSQL 15+)
--
--  Ogni notifica inviata (nuova opportunità sopra soglia, calo di prezzo)
--  viene registrata qui: il vincolo (listing_id, alert_type) garantisce che
--  lo stesso annuncio non venga mai rinotificato per lo stesso motivo,
--  anche se lo sniper lo rivede a ogni giro. Idempotente.
-- =====================================================================

create table if not exists public.sent_alerts (
  id          uuid primary key default gen_random_uuid(),
  listing_id  uuid not null,             -- id dell'opportunità (auto o tech)
  alert_type  text not null,             -- 'new_deal' | 'price_drop'
  category    text,                      -- 'smartphone' | 'automobile'
  margin_pct  numeric(6,1),              -- margine al momento dell'invio
  sent_at     timestamptz not null default now(),

  constraint uq_sent_alerts_listing_type unique (listing_id, alert_type)
);

comment on table public.sent_alerts is
  'Registro notifiche inviate: dedup per (listing_id, alert_type).';

create index if not exists idx_sent_alerts_sent
  on public.sent_alerts (sent_at desc);

alter table public.sent_alerts enable row level security;

drop policy if exists "sent_alerts_read_authenticated" on public.sent_alerts;
create policy "sent_alerts_read_authenticated"
  on public.sent_alerts for select
  to authenticated
  using ( true );

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 13
-- =====================================================================
