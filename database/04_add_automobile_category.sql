-- =====================================================================
--  MIGRAZIONE 04 — Nuova categoria nativa 'automobile'
--  Target: Supabase (PostgreSQL 15+)
--  Aggiunge il valore 'automobile' all'enum product_category per il nuovo
--  mercato auto con strict_filters (anno/km/cambio) salvati in products.specs.
--
--  NB: ALTER TYPE ... ADD VALUE non può girare dentro una transazione in
--  alcune versioni; nell'SQL Editor di Supabase (autocommit) funziona.
-- =====================================================================

alter type public.product_category add value if not exists 'automobile';

-- =====================================================================
-- FINE MIGRAZIONE 04
-- =====================================================================
