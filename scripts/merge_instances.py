"""Merge additivo di un'istanza secondaria (es. un altro PC) nel DB principale.

Contesto: il DB principale (con settimane di storico) vive su una macchina; una
seconda istanza gira altrove e accumula dati in parallelo. Le due condividono lo
stesso schema ma NON gli stessi UUID: ogni istanza genera i propri. Questo script
porta nel TARGET (principale) solo ciò che gli MANCA, senza toccare ciò che ha già.

Cosa fa, in ordine:
  1. TARGET_MODELS — rimappa i target per NOME ``(category, query)``, non per UUID.
     I target presenti in SOURCE ma non nel TARGET vengono inseriti (mantenendo il
     loro UUID) così gli annunci collegati restano validi.
  2. OPPORTUNITÀ (_tech e _auto) — inserisce solo gli annunci NUOVI, dedup su
     ``listing_url`` (ON CONFLICT DO NOTHING: gli annunci già nel TARGET restano
     quelli del principale). ``target_id`` viene rimappato.
  3. PRICE_HISTORY — porta lo storico prezzi dei soli annunci effettivamente
     inseriti (evita orfani).

Cosa NON tocca (di proposito):
  - Annunci già presenti nel TARGET (stesso ``listing_url``): non sovrascritti.
  - ``market_trends``: aggregato RICALCOLABILE → NON unito. Dopo il merge esegui
    il batch notturno sul principale per rigenerarlo.
  - ``sent_alerts`` (dedup Telegram) e ``deals`` (pipeline): stato locale, ignorati.

Proprietà: idempotente (rilanciarlo non duplica nulla) e atomico (una sola
transazione sul TARGET: o va tutto, o niente).

------------------------------------------------------------------------------
USO (sul principale, dopo aver ripristinato il dump del secondo PC in un DB
temporaneo — es. ``reseller_pc``):

  # 1) SEMPRE un backup del principale prima di scrivere:
  pg_dump "$TARGET_DATABASE_URL" -Fc -f backup_principale_$(date +%F).dump

  # 2) Anteprima (non scrive niente):
  SOURCE_DATABASE_URL=postgresql://postgres:PWD@localhost:5432/reseller_pc \
  TARGET_DATABASE_URL=postgresql://postgres:PWD@localhost:5432/reseller \
  python scripts/merge_instances.py --dry-run

  # 3) Applica:
  SOURCE_DATABASE_URL=... TARGET_DATABASE_URL=... \
  python scripts/merge_instances.py --yes

  # 4) Rigenera gli aggregati sul principale (una volta):
  #    dall'app: attendi il batch notturno, oppure lancia il nightly batch.
------------------------------------------------------------------------------
"""

from __future__ import annotations

import argparse
import os
import sys

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

OPP_TABLES = ("live_opportunities_tech", "live_opportunities_auto")


def _connect(url: str, name: str) -> psycopg.Connection:
    if not url:
        sys.exit(f"ERRORE: {name} non impostata (variabile d'ambiente o --{name.lower()}).")
    try:
        return psycopg.connect(url, row_factory=dict_row, autocommit=False)
    except Exception as exc:  # noqa: BLE001
        sys.exit(f"ERRORE: connessione a {name} fallita: {exc}")


def _columns(conn: psycopg.Connection, table: str) -> dict[str, str]:
    """Nome colonna → data_type, dallo schema informativo (per intersezione e jsonb)."""
    rows = conn.execute(
        """
        select column_name, data_type
        from information_schema.columns
        where table_schema = 'public' and table_name = %s
        """,
        (table,),
    ).fetchall()
    return {r["column_name"]: r["data_type"] for r in rows}


def _wrap(value: object, is_json: bool) -> object:
    """Avvolge i valori jsonb per psycopg; lascia intatto il resto."""
    if is_json and value is not None:
        return Jsonb(value)
    return value


def _remap_targets(
    src: psycopg.Connection, tgt: psycopg.Connection, tgt_cur: psycopg.Cursor, dry: bool
) -> tuple[dict[str, str], int]:
    """Costruisce src_target_id → tgt_target_id per NOME (category, query).

    I target di SOURCE assenti nel TARGET vengono inseriti (stesso UUID) così le
    FK degli annunci restano valide. Ritorna (mappa, n_target_inseriti)."""
    src_targets = src.execute(
        "select id, category, query, strict_filters, is_active from target_models"
    ).fetchall()
    tgt_by_key = {
        (r["category"], r["query"]): r["id"]
        for r in tgt.execute("select id, category, query from target_models").fetchall()
    }

    mapping: dict[str, str] = {}
    inserted = 0
    for t in src_targets:
        key = (t["category"], t["query"])
        if key in tgt_by_key:
            mapping[t["id"]] = tgt_by_key[key]
            continue
        # Target sconosciuto al principale: portalo (stesso UUID → nessuna collisione).
        mapping[t["id"]] = t["id"]
        inserted += 1
        if not dry:
            tgt_cur.execute(
                """
                insert into target_models (id, category, query, strict_filters, is_active)
                values (%s, %s, %s, %s, %s)
                on conflict (category, query) do nothing
                """,
                (t["id"], t["category"], t["query"], _wrap(t["strict_filters"], True), t["is_active"]),
            )
    return mapping, inserted


def _merge_opportunities(
    src: psycopg.Connection,
    tgt: psycopg.Connection,
    tgt_cur: psycopg.Cursor,
    table: str,
    target_map: dict[str, str],
    dry: bool,
) -> tuple[int, int, set[str]]:
    """Inserisce gli annunci NUOVI (dedup listing_url). Ritorna
    (candidati, inseriti, id_annunci_validi_nel_target)."""
    src_cols = _columns(src, table)
    tgt_cols = _columns(tgt, table)
    if not src_cols or not tgt_cols:
        return 0, 0, set()
    # Solo colonne presenti in entrambi (robusto a piccole differenze di schema).
    cols = [c for c in src_cols if c in tgt_cols]
    json_cols = {c for c in cols if src_cols[c] == "jsonb"}

    rows = src.execute(f"select * from {table}").fetchall()  # noqa: S608 (nome tabella fisso)
    if not rows:
        return 0, 0, set()

    col_list = ", ".join(cols)
    placeholders = ", ".join(["%s"] * len(cols))
    insert_sql = (
        f"insert into {table} ({col_list}) values ({placeholders}) "  # noqa: S608
        f"on conflict (listing_url) do nothing"
    )

    src_ids: list[str] = []
    inserted = 0
    for row in rows:
        # Rimappa target_id (se assente dalla mappa, salta: FK non valida).
        tid = row.get("target_id")
        if tid is not None:
            mapped = target_map.get(tid)
            if mapped is None:
                continue
            row["target_id"] = mapped
        src_ids.append(row["id"])
        if not dry:
            params = [_wrap(row.get(c), c in json_cols) for c in cols]
            tgt_cur.execute(insert_sql, params)
            inserted += tgt_cur.rowcount or 0

    # Quali degli id di SOURCE risultano ora presenti nel TARGET (= inseriti da
    # noi): serve a filtrare il price_history ed evitare orfani.
    valid_ids: set[str] = set()
    if src_ids:
        conn_for_check = tgt if not dry else src
        present = conn_for_check.execute(
            f"select id from {table} where id = any(%s)",  # noqa: S608
            (src_ids,),
        ).fetchall()
        valid_ids = {r["id"] for r in present}
    return len(src_ids), inserted, valid_ids


def _merge_price_history(
    src: psycopg.Connection,
    tgt_cur: psycopg.Cursor,
    valid_listing_ids: set[str],
    dry: bool,
) -> int:
    """Porta lo storico prezzi dei soli annunci inseriti (dedup su id)."""
    if not valid_listing_ids:
        return 0
    rows = src.execute(
        "select id, listing_id, old_price, new_price, changed_at from price_history "
        "where listing_id = any(%s)",
        (list(valid_listing_ids),),
    ).fetchall()
    if dry:
        return len(rows)
    inserted = 0
    for r in rows:
        tgt_cur.execute(
            """
            insert into price_history (id, listing_id, old_price, new_price, changed_at)
            values (%s, %s, %s, %s, %s)
            on conflict (id) do nothing
            """,
            (r["id"], r["listing_id"], r["old_price"], r["new_price"], r["changed_at"]),
        )
        inserted += tgt_cur.rowcount or 0
    return inserted


def main() -> None:
    ap = argparse.ArgumentParser(description="Merge additivo di una seconda istanza nel DB principale.")
    ap.add_argument("--source", default=os.getenv("SOURCE_DATABASE_URL", ""))
    ap.add_argument("--target", default=os.getenv("TARGET_DATABASE_URL", ""))
    ap.add_argument("--dry-run", action="store_true", help="Mostra cosa farebbe, senza scrivere.")
    ap.add_argument("--yes", action="store_true", help="Applica davvero (conferma richiesta).")
    args = ap.parse_args()

    if not args.dry_run and not args.yes:
        sys.exit("Sicurezza: usa --dry-run per l'anteprima, o --yes per applicare. "
                 "E fai PRIMA un pg_dump del principale.")

    src = _connect(args.source, "SOURCE_DATABASE_URL")
    tgt = _connect(args.target, "TARGET_DATABASE_URL")
    dry = args.dry_run

    print(f"{'ANTEPRIMA (nessuna scrittura)' if dry else 'MERGE IN CORSO'}")
    print(f"  SOURCE = {args.source.rsplit('@', 1)[-1]}")
    print(f"  TARGET = {args.target.rsplit('@', 1)[-1]}\n")

    tgt_cur = tgt.cursor()
    try:
        target_map, new_targets = _remap_targets(src, tgt, tgt_cur, dry)
        print(f"target_models: {len(target_map)} mappati per nome, {new_targets} nuovi da portare")

        grand_new = 0
        all_valid_ids: set[str] = set()
        for table in OPP_TABLES:
            cand, ins, valid = _merge_opportunities(src, tgt, tgt_cur, table, target_map, dry)
            all_valid_ids |= valid
            shown = ins if not dry else cand
            print(f"{table}: {cand} candidati → {shown} {'inseriti' if not dry else 'nuovi (stima)'}")
            grand_new += shown

        hist = _merge_price_history(src, tgt_cur, all_valid_ids, dry)
        print(f"price_history: {hist} righe {'inserite' if not dry else '(stima)'}")

        if dry:
            tgt.rollback()
            print("\nAnteprima completata: NIENTE è stato scritto. Rilancia con --yes per applicare.")
        else:
            tgt.commit()
            print(f"\nMerge COMPLETATO: {grand_new} annunci nuovi + {hist} righe di storico + "
                  f"{new_targets} target.\nAdesso rigenera market_trends sul principale "
                  "(batch notturno) e verifica in UI.")
    except Exception as exc:  # noqa: BLE001
        tgt.rollback()
        sys.exit(f"\nERRORE durante il merge (rollback eseguito, TARGET intatto): {exc}")
    finally:
        src.close()
        tgt.close()


if __name__ == "__main__":
    main()
