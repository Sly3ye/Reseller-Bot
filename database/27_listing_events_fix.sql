-- =====================================================================
--  MIGRAZIONE 27 — listing_events: niente "ripubblicato" per i rinomi
--                  temporanei della fusione dei doppioni
--  Target: PostgreSQL self-hosted (Docker)
--
--  La fusione delle ripubblicazioni (services/republish.py) sposta prima il
--  gemello su un URL temporaneo "...#ripubblicato-<id>" per liberare il
--  vincolo unique, poi dà l'URL nuovo al record originale e cancella il
--  gemello. Il primo passo non è una ripubblicazione: il 5/10 raddoppiava gli
--  eventi (748 "ripubblicato" per 374 fusioni). Ora i cambi verso un URL con
--  '#' si saltano, e quelli già registrati si cancellano. Solo la funzione
--  del trigger cambia: nessuna colonna sulle tabelle degli annunci.
--  Idempotente.
-- =====================================================================

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
    -- Rinomina temporanea della fusione (URL con '#'): nessun evento.
    if position('#' in new.listing_url) = 0 then
      insert into public.listing_events (listing_id, category, kind, price, old_price, info)
      values (new.id, cat, 'ripubblicato', new.asking_price, old.asking_price,
              jsonb_build_object('old_url', split_part(old.listing_url, '#', 1), 'new_url', new.listing_url,
                                 'was_removed', not was_active));
    end if;
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

delete from public.listing_events where kind = 'ripubblicato' and info->>'new_url' like '%#%';
