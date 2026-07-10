-- =====================================================================
--  MIGRAZIONE 07 — Tabella price_history (storico cali di prezzo)
--  Target: Supabase (PostgreSQL 15+)
--  Risultava assente dalla schema cache: questo la crea (idempotente).
--  Colonne come da DDL fornito. Dopo, ricarica lo schema di PostgREST.
-- =====================================================================

create table if not exists public.price_history (
    id         uuid primary key,
    listing_id uuid not null,
    old_price  numeric not null,
    new_price  numeric not null,
    changed_at timestamptz default now()
);

create index if not exists idx_price_history_listing
  on public.price_history (listing_id, changed_at desc);

-- Ricarica la cache dello schema così PostgREST/Supabase vede subito la tabella.
notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 07
-- =====================================================================
