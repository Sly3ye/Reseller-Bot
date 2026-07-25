"""Test della generazione SQL dello shim psycopg (backend/core/database.py).

Verifica che il query-builder compatibile con supabase-py produca l'SQL
atteso, senza bisogno di un database attivo (testa Query.build()).

Esegui dalla root:  python scripts/test_db_shim.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from psycopg.types.json import Jsonb  # noqa: E402

from backend.core.database import Query, _adapt  # noqa: E402

_passed = 0
_failed = 0


def check(desc, got, want):
    global _passed, _failed
    ok = got == want
    _passed += ok
    _failed += not ok
    print(f"  {'OK  ' if ok else 'FAIL'} {desc}")
    if not ok:
        print(f"       got:  {got!r}")
        print(f"       want: {want!r}")


def norm(sql: str) -> str:
    return " ".join(sql.split())


print("SELECT:")
sql, params = Query("products").select("id, model").eq("category", "smartphone").build()
check("select + eq", (norm(sql), params),
      ('select id, model from "products" where "category" = %s', ["smartphone"]))

sql, params = Query("t").select("*").in_("status", ["nuovo", "visto"]).build()
check("in_ non vuoto", (norm(sql), params),
      ('select * from "t" where "status" in (%s, %s)', ["nuovo", "visto"]))

sql, params = Query("t").select("*").in_("status", []).build()
check("in_ vuoto → false", (norm(sql), params), ('select * from "t" where false', []))

sql, params = Query("t").select("*").order("found_at", desc=True).limit(60).build()
check("order desc + limit", norm(sql),
      'select * from "t" order by "found_at" desc limit 60')

sql, params = Query("t").select("id, listing_url").range(0, 999).build()
check("range → limit/offset", norm(sql),
      'select id, listing_url from "t" limit 1000 offset 0')

sql, params = (
    Query("t").select("km, asking_price")
    .eq("target_id", "x").in_("status", ["nuovo"]).not_.is_("km", "null")
    .limit(500).build()
)
check("not_.is_ null", norm(sql),
      'select km, asking_price from "t" where "target_id" = %s and "status" in (%s) '
      'and not ("km" is null) limit 500')

print("INSERT:")
sql, params = Query("t").insert({"a": 1, "b": "x"}).build()
check("insert singolo", norm(sql),
      'insert into "t" ("a", "b") values (%s, %s) returning *')
check("insert params", params, [1, "x"])

sql, params = Query("t").insert([{"a": 1}, {"a": 2}]).build()
check("insert multi-row", norm(sql),
      'insert into "t" ("a") values (%s), (%s) returning *')
check("insert multi params", params, [1, 2])

print("UPSERT:")
sql, params = (
    Query("sent_alerts")
    .upsert({"listing_id": "L", "alert_type": "new_deal"},
            on_conflict="listing_id,alert_type", ignore_duplicates=True)
    .build()
)
check("upsert ignore → do nothing", norm(sql),
      'insert into "sent_alerts" ("listing_id", "alert_type") values (%s, %s) '
      'on conflict ("listing_id", "alert_type") do nothing returning *')

sql, params = (
    Query("market_trends")
    .upsert({"target_id": "T", "trend_date": "2026-07-18", "avg_price": 100},
            on_conflict="target_id,trend_date")
    .build()
)
check("upsert → do update set (esclude chiavi)", norm(sql),
      'insert into "market_trends" ("target_id", "trend_date", "avg_price") '
      'values (%s, %s, %s) on conflict ("target_id", "trend_date") '
      'do update set "avg_price" = excluded."avg_price" returning *')

print("UPDATE / DELETE:")
sql, params = Query("t").update({"status": "visto"}).eq("id", "X").build()
check("update + eq", (norm(sql), params),
      ('update "t" set "status" = %s where "id" = %s returning *', ["visto", "X"]))

sql, params = Query("t").delete().eq("id", "X").build()
check("delete + eq", (norm(sql), params),
      ('delete from "t" where "id" = %s returning *', ["X"]))

print("JSONB:")
adapted = _adapt(["a", "b"])
check("lista → Jsonb", isinstance(adapted, Jsonb), True)
adapted = _adapt({"k": 1})
check("dict → Jsonb", isinstance(adapted, Jsonb), True)
check("scalare invariato", _adapt(42), 42)

# Un insert con valore JSONB deve wrappare quel parametro in Jsonb.
sql, params = Query("t").insert({"image_urls": ["u1", "u2"], "title": "x"}).build()
check("insert jsonb param wrappato", isinstance(params[0], Jsonb), True)
check("insert scalar param non wrappato", params[1], "x")

print(f"\n=== {_passed} PASS / {_failed} FAIL ===")
raise SystemExit(1 if _failed else 0)
