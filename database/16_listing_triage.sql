-- =====================================================================
--  MIGRAZIONE 16 — triage utente sugli annunci (salva / scarta)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Colonna ORTOGONALE al lifecycle `status` (nuovo/visto/scaduto/venduto):
--  registra l'azione dell'utente sul feed. NULL = nessuna azione,
--  'salvato' = messo tra i preferiti, 'scartato' = nascosto dal feed.
--  Idempotente.
-- =====================================================================

alter table public.live_opportunities_auto
  add column if not exists triage text;
alter table public.live_opportunities_tech
  add column if not exists triage text;

create index if not exists idx_auto_triage
  on public.live_opportunities_auto (triage);
create index if not exists idx_tech_triage
  on public.live_opportunities_tech (triage);

-- =====================================================================
-- FINE MIGRAZIONE 16
-- =====================================================================
