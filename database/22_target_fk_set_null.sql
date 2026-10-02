-- =====================================================================
--  MIGRAZIONE 22 — cancellare un target non cancella più i suoi annunci
--  Target: PostgreSQL self-hosted (Docker)
--
--  live_opportunities_*.target_id era ON DELETE CASCADE: una DELETE di un
--  target (anche a mano) cancellava tutto lo storico di quel modello —
--  venduti, tempi di vendita, prezzi. Ora il riferimento si azzera e le
--  righe restano (il modello si ricava comunque dal titolo). Idempotente.
-- =====================================================================

alter table public.live_opportunities_tech
  drop constraint if exists live_opportunities_tech_target_id_fkey;
alter table public.live_opportunities_tech
  add constraint live_opportunities_tech_target_id_fkey
  foreign key (target_id) references public.target_models(id) on delete set null;

alter table public.live_opportunities_auto
  drop constraint if exists live_opportunities_auto_target_id_fkey;
alter table public.live_opportunities_auto
  add constraint live_opportunities_auto_target_id_fkey
  foreign key (target_id) references public.target_models(id) on delete set null;
