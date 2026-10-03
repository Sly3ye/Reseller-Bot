-- =====================================================================
--  MIGRAZIONE 29 — identità del target = (category, query, strict_filters)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Lo stesso modello può avere più target, uno per generazione, distinti dai
--  filtri (es. "BMW 125i" 2007–2013 e 2012–2019): le statistiche restano
--  isolate per generazione. Il vincolo su (category, query) lo impediva ed era
--  diverso tra le macchine (Mac già con strict_filters). Per gli iPhone
--  (filtri vuoti) non cambia nulla. Idempotente.
-- =====================================================================

alter table public.target_models
  drop constraint if exists uq_target_models_identity;
alter table public.target_models
  add constraint uq_target_models_identity unique (category, query, strict_filters);

-- =====================================================================
-- FINE MIGRAZIONE 29
-- =====================================================================
