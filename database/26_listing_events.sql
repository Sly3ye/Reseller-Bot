-- =====================================================================
--  MIGRAZIONE 26 — listing_events: la storia di ogni annuncio, in sola
--                  aggiunta (Goal Version §2, "Il database per le serie
--                  storiche")
--  Target: PostgreSQL self-hosted (Docker)
--
--  Le righe degli annunci sono mutabili (prezzo sovrascritto, updated_at =
--  ultima vista): la storia si perdeva. Da qui in poi ogni cambiamento
--  lascia un evento:
--    comparso      inserimento (at = found_at)
--    prezzo        asking_price cambiato (old_price → price)
--    sparito       da attivo a venduto_rimosso/scaduto
--    ricomparso    da rimosso ad attivo, stesso annuncio
--    ripubblicato  stesso oggetto rimesso online con un nuovo annuncio (URL)
--    fuso          riga eliminata perché doppione di un'altra
--    riposizionato data mostrata da Subito spostata in avanti (lo scrive
--                  l'applicazione: la colonna published_at resta la prima)
--  Trigger nel DB, non nel codice: catturano ogni percorso di scrittura
--  (raccolta, inventari, GC, merge, script) anche di versioni vecchie del
--  raccoglitore. Un errore nel trigger non blocca mai la scrittura
--  dell'annuncio (avviso nel log di Postgres). Nessuna colonna nuova sulle
--  tabelle degli annunci. Idempotente.
-- =====================================================================

create table if not exists public.listing_events (
  id         bigserial primary key,
  listing_id uuid        not null,
  category   text        not null,          -- 'smartphone' | 'automobile'
  kind       text        not null,
  at         timestamptz not null default now(),
  price      numeric(12, 2),                -- prezzo dopo l'evento
  old_price  numeric(12, 2),                -- prezzo prima (prezzo, ripubblicato)
  info       jsonb
);

create index if not exists idx_listing_events_listing on public.listing_events (listing_id, at);
create index if not exists idx_listing_events_kind_at on public.listing_events (kind, at desc);

comment on table public.listing_events is
  'Storia degli annunci in sola aggiunta: comparso, prezzo, sparito, ricomparso, ripubblicato, fuso, riposizionato.';

create or replace function public.fr_listing_events() returns trigger
language plpgsql as $$
declare
  cat        text := tg_argv[0];
  was_active boolean;
  is_active  boolean;
begin
  if tg_op = 'INSERT' then
    insert into public.listing_events (listing_id, category, kind, at, price, info)
    values (new.id, cat, 'comparso', coalesce(new.found_at, now()), new.asking_price,
            jsonb_build_object('published_at', new.published_at));
    return null;
  elsif tg_op = 'DELETE' then
    insert into public.listing_events (listing_id, category, kind, price, info)
    values (old.id, cat, 'fuso', old.asking_price, jsonb_build_object('listing_url', old.listing_url));
    return null;
  end if;

  was_active := old.status::text in ('nuovo', 'visto');
  is_active  := new.status::text in ('nuovo', 'visto');
  if new.listing_url is distinct from old.listing_url then
    insert into public.listing_events (listing_id, category, kind, price, old_price, info)
    values (new.id, cat, 'ripubblicato', new.asking_price, old.asking_price,
            jsonb_build_object('old_url', old.listing_url, 'new_url', new.listing_url,
                               'was_removed', not was_active));
  else
    if was_active and not is_active then
      insert into public.listing_events (listing_id, category, kind, price, info)
      values (new.id, cat, 'sparito', new.asking_price, jsonb_build_object('status', new.status::text));
    elsif is_active and not was_active then
      insert into public.listing_events (listing_id, category, kind, price)
      values (new.id, cat, 'ricomparso', new.asking_price);
    end if;
    if new.asking_price is distinct from old.asking_price then
      insert into public.listing_events (listing_id, category, kind, price, old_price)
      values (new.id, cat, 'prezzo', new.asking_price, old.asking_price);
    end if;
  end if;
  return null;
exception when others then
  raise warning 'listing_events non registrato (%): %', tg_op, sqlerrm;
  return null;
end;
$$;

drop trigger if exists trg_listing_events on public.live_opportunities_tech;
create trigger trg_listing_events
  after insert or delete or update of asking_price, status, listing_url
  on public.live_opportunities_tech
  for each row execute function public.fr_listing_events('smartphone');

drop trigger if exists trg_listing_events on public.live_opportunities_auto;
create trigger trg_listing_events
  after insert or delete or update of asking_price, status, listing_url
  on public.live_opportunities_auto
  for each row execute function public.fr_listing_events('automobile');

-- Storia di partenza dai dati già raccolti (solo se la tabella è vuota):
-- comparsa al found_at col primo prezzo noto, i cambi di price_history, la
-- sparizione all'ultimo aggiornamento (approssimata).
do $$
begin
  if exists (select 1 from public.listing_events limit 1) then
    return;
  end if;

  insert into public.listing_events (listing_id, category, kind, at, price, info)
  select t.id, t.cat, 'comparso', t.found_at,
         coalesce((select ph.old_price from public.price_history ph
                   where ph.listing_id = t.id order by ph.changed_at limit 1), t.asking_price),
         jsonb_build_object('published_at', t.published_at, 'backfill', true)
  from (select id, found_at, asking_price, published_at, 'smartphone' as cat from public.live_opportunities_tech
        union all
        select id, found_at, asking_price, published_at, 'automobile' from public.live_opportunities_auto) t;

  insert into public.listing_events (listing_id, category, kind, at, price, old_price, info)
  select ph.listing_id, case when tech.id is not null then 'smartphone' else 'automobile' end,
         'prezzo', ph.changed_at, ph.new_price, ph.old_price, '{"backfill": true}'::jsonb
  from public.price_history ph
  left join public.live_opportunities_tech tech on tech.id = ph.listing_id
  left join public.live_opportunities_auto auto on auto.id = ph.listing_id
  where tech.id is not null or auto.id is not null;

  insert into public.listing_events (listing_id, category, kind, at, price, info)
  select id, cat, 'sparito', updated_at, asking_price, jsonb_build_object('status', status::text, 'backfill', true)
  from (select id, updated_at, asking_price, status, 'smartphone' as cat from public.live_opportunities_tech
        union all
        select id, updated_at, asking_price, status, 'automobile' from public.live_opportunities_auto) t
  where status::text not in ('nuovo', 'visto');
end $$;
