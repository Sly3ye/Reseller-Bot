-- =====================================================================
--  MIGRAZIONE 28 — archivio degli annunci iPhone fuori ambito
--  Target: PostgreSQL self-hosted (Docker)
--
--  Il 5/10 l'ambito iPhone torna "dal 12 in su" (sotto: poco giro e poco
--  margine) e fuori restano anche accessori e altri marchi. Gli annunci già
--  raccolti non si cancellano: si spostano qui (services/scope.py), così
--  feed, statistiche, inventario e foto lavorano solo sull'ambito, e se
--  l'ambito cambia si rimettono al loro posto. Stessa struttura della tabella
--  degli annunci più motivo e data dello spostamento. Idempotente.
-- =====================================================================

create table if not exists public.live_opportunities_tech_archivio
  (like public.live_opportunities_tech including all);

alter table public.live_opportunities_tech_archivio
  add column if not exists archived_at timestamptz not null default now();
alter table public.live_opportunities_tech_archivio
  add column if not exists archived_reason text;

comment on table public.live_opportunities_tech_archivio is
  'Annunci iPhone fuori ambito (sotto IPHONE_MIN_GEN, accessori, altri marchi): spostati, non cancellati.';
