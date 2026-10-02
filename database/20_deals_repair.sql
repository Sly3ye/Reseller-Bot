-- =====================================================================
--  MIGRAZIONE 20 — deals: stima del bot e riparazione reale (E2 release)
--  Target: PostgreSQL self-hosted (Docker)
--
--  estimate: la stima fotografata quando l'annuncio entra in pipeline
--            (margine, ricambi previsti, rivendita del riparato, tetto) →
--            confronto stima/realtà onesto anche se i listini cambiano dopo.
--  repair:   la riparazione vera: pezzi montati (fonte + costo), minuti di
--            lavoro, esito (riuscita / parziale / fallita), note.
--  Idempotente.
-- =====================================================================

alter table public.deals add column if not exists estimate jsonb;
alter table public.deals add column if not exists repair jsonb;
