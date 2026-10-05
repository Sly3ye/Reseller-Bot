-- =====================================================================
--  MIGRAZIONE 25 — alert consegnati davvero, azioni da Telegram, emivita
--                  degli affari, budget delle richieste (Goal Version P0/P1)
--  Target: PostgreSQL self-hosted (Docker)
--
--  sent_alerts: prima si segnava "inviato" PRIMA di inviare: un invio
--  fallito era perso per sempre e invisibile. Ora: esito della consegna,
--  id del messaggio (per i bottoni e le risposte all'alert), e per gli affari
--  segnalati quando spariscono (emivita = quanto dura un'occasione).
--  request_log: richieste e blocchi per job e per giorno, per sapere quanto
--  budget consuma ogni lavoro dallo stesso IP. Idempotente.
-- =====================================================================

alter table public.sent_alerts add column if not exists delivered boolean;
alter table public.sent_alerts add column if not exists telegram_msg_id bigint;
alter table public.sent_alerts add column if not exists chat_id text;
alter table public.sent_alerts add column if not exists gone_at timestamptz;
alter table public.sent_alerts add column if not exists last_checked_at timestamptz;
create index if not exists idx_sent_alerts_msg on public.sent_alerts (chat_id, telegram_msg_id);

create table if not exists public.request_log (
  day      date    not null,
  job      text    not null,
  requests integer not null default 0,
  blocks   integer not null default 0,
  primary key (day, job)
);
