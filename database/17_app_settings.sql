-- =====================================================================
--  MIGRAZIONE 17 — app_settings (impostazioni configurabili da UI)
--  Target: PostgreSQL self-hosted (Docker)
--
--  Chiave→valore JSON per i parametri che l'utente può cambiare senza toccare
--  il codice: soglie alert, margine obiettivo, prezzi ricambi Apple, chat
--  Telegram. Una sola riga per chiave; i default vivono nel codice
--  (backend/services/settings_store.py) e questa tabella li sovrascrive.
--  Idempotente.
-- =====================================================================

create table if not exists public.app_settings (
  key        text primary key,
  value      jsonb not null,
  updated_at timestamptz not null default now()
);

-- =====================================================================
-- FINE MIGRAZIONE 17
-- =====================================================================
