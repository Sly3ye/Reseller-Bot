-- =====================================================================
--  MIGRAZIONE 11 — nuovo stato 'venduto_rimosso' (Garbage Collector)
--  Target: Supabase (PostgreSQL 15+)
--
--  L'enum opportunity_status era ('nuovo','visto','scaduto'). Il Garbage
--  Collector marca gli annunci non più raggiungibili (404/redirect) come
--  'venduto_rimosso': aggiungiamo il valore all'enum. Idempotente.
--
--  NB: ADD VALUE non può girare dentro una transazione esplicita; eseguire
--  questa istruzione da sola (l'editor SQL di Supabase va bene).
-- =====================================================================

alter type public.opportunity_status add value if not exists 'venduto_rimosso';

notify pgrst, 'reload schema';

-- =====================================================================
-- FINE MIGRAZIONE 11
-- =====================================================================
