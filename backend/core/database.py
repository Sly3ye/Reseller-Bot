"""Accesso dati self-hosted (PostgreSQL via psycopg) + storage immagini su disco.

Sostituisce Supabase mantenendo **la stessa API** del client `supabase-py`
(`db.table(...).select(...).eq(...).execute()`), così i ~60 call site del
codice restano invariati: cambia solo cosa c'è sotto (un pool psycopg verso il
tuo Postgres, in locale o sul VPS) invece del REST di Supabase.

Lo shim replica fedelmente il comportamento osservabile di PostgREST:
- `.execute()` ritorna un oggetto con ``.data`` (list[dict]) e ``.count`` (int|None);
- insert/update/upsert/delete ritornano le righe interessate (``RETURNING *``);
- i valori JSONB (liste/dict) sono adattati automaticamente;
- in uscita i tipi sono normalizzati come li dava Supabase: timestamp/date →
  stringa ISO, ``Decimal`` → float, ``UUID`` → str.

Gli identificatori (tabelle/colonne) provengono solo dal codice, mai
dall'utente, quindi il quoting manuale è sicuro; i valori passano sempre come
parametri ``%s``.
"""

from __future__ import annotations

import atexit
import os
import threading
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable
from uuid import UUID

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from backend.core.config import settings

# ---------------------------------------------------------------- pool

_pool: ConnectionPool | None = None
_pool_lock = threading.Lock()


def _get_pool() -> ConnectionPool:
    """Pool di connessioni condiviso e thread-safe (creato al primo uso).

    ``dict_row`` fa tornare ogni riga come dict (come faceva Supabase). Il
    context manager ``pool.connection()`` committa a fine blocco se non ci sono
    eccezioni, altrimenti fa rollback.
    """
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ConnectionPool(
                    settings.database_url,
                    min_size=1,
                    max_size=int(os.getenv("DB_POOL_MAX", "10")),
                    kwargs={"row_factory": dict_row},
                    open=True,
                )
                atexit.register(_close_pool)
    return _pool


def _close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


# ------------------------------------------------------------ adattamento

def _adapt(value: Any) -> Any:
    """Adatta un valore Python per il bind: liste/dict → JSONB."""
    if isinstance(value, (dict, list)):
        return Jsonb(value)
    return value


def _normalize(value: Any) -> Any:
    """Normalizza un valore letto dal DB come lo restituiva Supabase (JSON)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    return {k: _normalize(v) for k, v in row.items()}


def _quote_ident(name: str) -> str:
    """Quoting sicuro di un identificatore (nomi da codice, non da utente)."""
    return '"' + name.replace('"', '""') + '"'


# ------------------------------------------------------------- response

class Response:
    """Equivalente di APIResponse di supabase-py: ``.data`` e ``.count``."""

    def __init__(self, data: list[dict[str, Any]], count: int | None = None) -> None:
        self.data = data
        self.count = count


# --------------------------------------------------------------- query

class Query:
    """Costruttore di query con la stessa fluent-API di supabase-py."""

    def __init__(self, table: str) -> None:
        self._table = table
        self._op = "select"
        self._columns = "*"
        self._count_mode: str | None = None
        self._filters: list[tuple[str, list[Any]]] = []
        self._orders: list[tuple[str, bool]] = []
        self._limit: int | None = None
        self._range: tuple[int, int] | None = None
        self._payload: dict | list | None = None
        self._on_conflict: str | None = None
        self._ignore_duplicates = False
        self._negate_next = False

    # -- operazioni -------------------------------------------------------
    def select(self, columns: str = "*", count: str | None = None) -> "Query":
        # Dopo insert/update/upsert/delete, un eventuale select() non cambia
        # l'operazione (RETURNING * copre già il "representation").
        if self._op == "select":
            self._columns = columns
        if count:
            self._count_mode = count
        return self

    def insert(self, payload: dict | list) -> "Query":
        self._op = "insert"
        self._payload = payload
        return self

    def update(self, patch: dict) -> "Query":
        self._op = "update"
        self._payload = patch
        return self

    def upsert(
        self,
        payload: dict | list,
        on_conflict: str | None = None,
        ignore_duplicates: bool = False,
    ) -> "Query":
        self._op = "upsert"
        self._payload = payload
        self._on_conflict = on_conflict
        self._ignore_duplicates = ignore_duplicates
        return self

    def delete(self) -> "Query":
        self._op = "delete"
        return self

    # -- filtri -----------------------------------------------------------
    def eq(self, column: str, value: Any) -> "Query":
        self._filters.append((f"{_quote_ident(column)} = %s", [value]))
        return self

    def neq(self, column: str, value: Any) -> "Query":
        self._filters.append((f"{_quote_ident(column)} <> %s", [value]))
        return self

    def in_(self, column: str, values: Iterable[Any]) -> "Query":
        vals = list(values)
        if not vals:
            # supabase: in_() su lista vuota → nessuna riga.
            self._filters.append(("false", []))
        else:
            placeholders = ", ".join(["%s"] * len(vals))
            self._filters.append((f"{_quote_ident(column)} in ({placeholders})", vals))
        return self

    @property
    def not_(self) -> "Query":
        self._negate_next = True
        return self

    def is_(self, column: str, value: Any) -> "Query":
        if value is None or str(value).lower() == "null":
            frag = f"{_quote_ident(column)} is null"
            params: list[Any] = []
        else:
            frag = f"{_quote_ident(column)} is %s"
            params = [value]
        if self._negate_next:
            frag = f"not ({frag})"
            self._negate_next = False
        self._filters.append((frag, params))
        return self

    def order(self, column: str, desc: bool = False) -> "Query":
        self._orders.append((column, desc))
        return self

    def limit(self, n: int) -> "Query":
        self._limit = n
        return self

    def range(self, start: int, end: int) -> "Query":
        # supabase: range inclusivo [start, end].
        self._range = (start, end)
        return self

    # -- costruzione SQL --------------------------------------------------
    def _where(self) -> tuple[str, list[Any]]:
        if not self._filters:
            return "", []
        clauses = " and ".join(f for f, _ in self._filters)
        params: list[Any] = []
        for _, ps in self._filters:
            params.extend(ps)
        return " where " + clauses, params

    def _rows(self) -> list[dict]:
        if self._payload is None:
            return []
        return self._payload if isinstance(self._payload, list) else [self._payload]

    def build(self) -> tuple[str, list[Any]]:
        """Genera (sql, params). Pubblico per i test (non richiede un DB)."""
        table = _quote_ident(self._table)

        if self._op == "select":
            sql = f"select {self._columns} from {table}"
            where, params = self._where()
            sql += where
            if self._orders:
                sql += " order by " + ", ".join(
                    f"{_quote_ident(c)} {'desc' if d else 'asc'}" for c, d in self._orders
                )
            if self._range is not None:
                start, end = self._range
                sql += f" limit {end - start + 1} offset {start}"
            elif self._limit is not None:
                sql += f" limit {self._limit}"
            return sql, params

        if self._op in ("insert", "upsert"):
            rows = self._rows()
            if not rows:
                raise ValueError("insert/upsert senza payload")
            columns = list(rows[0].keys())
            col_sql = ", ".join(_quote_ident(c) for c in columns)
            placeholder_row = "(" + ", ".join(["%s"] * len(columns)) + ")"
            values_sql = ", ".join([placeholder_row] * len(rows))
            params = [_adapt(row[c]) for row in rows for c in columns]
            sql = f"insert into {table} ({col_sql}) values {values_sql}"
            if self._op == "upsert":
                target = self._on_conflict or ""
                conflict_cols = [c.strip() for c in target.split(",") if c.strip()]
                conflict_sql = (
                    "(" + ", ".join(_quote_ident(c) for c in conflict_cols) + ")"
                    if conflict_cols
                    else ""
                )
                if self._ignore_duplicates:
                    sql += f" on conflict {conflict_sql} do nothing".rstrip()
                else:
                    updatable = [c for c in columns if c not in conflict_cols]
                    set_sql = ", ".join(
                        f"{_quote_ident(c)} = excluded.{_quote_ident(c)}"
                        for c in updatable
                    ) or f"{_quote_ident(conflict_cols[0])} = excluded.{_quote_ident(conflict_cols[0])}"
                    sql += f" on conflict {conflict_sql} do update set {set_sql}"
            sql += " returning *"
            return sql, params

        if self._op == "update":
            patch = self._payload or {}
            set_sql = ", ".join(f"{_quote_ident(c)} = %s" for c in patch)
            set_params = [_adapt(v) for v in patch.values()]
            where, where_params = self._where()
            sql = f"update {table} set {set_sql}{where} returning *"
            return sql, set_params + where_params

        if self._op == "delete":
            where, params = self._where()
            sql = f"delete from {table}{where} returning *"
            return sql, params

        raise ValueError(f"operazione non supportata: {self._op}")

    def _count(self, conn: psycopg.Connection) -> int:
        where, params = self._where()
        sql = f"select count(*) as n from {_quote_ident(self._table)}{where}"
        with conn.cursor() as cur:
            cur.execute(sql, params)
            row = cur.fetchone()
        return int(row["n"]) if row else 0

    def execute(self) -> Response:
        sql, params = self.build()
        pool = _get_pool()
        with pool.connection() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall() if cur.description else []
            count = (
                self._count(conn)
                if self._op == "select" and self._count_mode == "exact"
                else None
            )
        data = [_normalize_row(r) for r in rows]
        return Response(data, count)


class DBClient:
    """Punto d'ingresso equivalente al client di supabase-py."""

    def table(self, name: str) -> Query:
        return Query(name)


# Alias di tipo usato nelle annotazioni al posto di ``supabase.Client``.
Client = DBClient

_client = DBClient()


def get_db() -> DBClient:
    """Ritorna il client DB (stateless; il pool sottostante è condiviso)."""
    return _client


# ------------------------------------------------------------ storage

def _media_root() -> Path:
    root = Path(settings.media_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def upload_image_to_storage(
    image_bytes: bytes,
    filename: str,
    *,
    content_type: str = "image/jpeg",
) -> str:
    """Salva i byte dell'immagine su disco e ritorna l'URL pubblico servito da
    FastAPI (`/media/...`). Sostituisce lo Storage di Supabase: nessun costo,
    nessun limite oltre lo spazio del disco. Re-scrapare lo stesso annuncio
    sovrascrive il file (stesso path)."""
    del content_type  # dedotto dall'estensione del filename, non serve qui
    destination = _media_root() / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(image_bytes)
    base = settings.public_media_base_url.rstrip("/")
    return f"{base}/media/{filename}"
