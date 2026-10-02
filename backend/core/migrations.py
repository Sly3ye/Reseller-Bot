"""Migration runner: applica all'avvio le migrazioni SQL non ancora applicate.

Prima le migrazioni andavano lanciate a mano, su due macchine (PC e Mac), e
dimenticarne una significava perdere dati in silenzio (il codice salta le
colonne che mancano). Ora:

- ``schema_migrations`` registra cosa è già stato applicato;
- all'avvio del backend si applicano in ordine i file ``database/NN_*.sql``
  mancanti, ognuno nella sua transazione (se uno fallisce si ferma lì e il
  backend parte lo stesso, segnalandolo nei log);
- i file 01–17 sono lo storico dell'istanza Supabase, già compresi in
  ``selfhosted/init.sql``: al primo giro vengono solo REGISTRATI (baseline),
  mai eseguiti.

Regola per le migrazioni nuove: devono essere IDEMPOTENTI (``if not exists``),
perché un DB nuovo le riceve sia da init.sql sia da qui.

Uso manuale: ``python scripts/migrate.py`` (stato) / ``--apply``.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "database"
# Ultima migrazione dell'era Supabase: da qui in giù è tutto in init.sql.
BASELINE_MAX = 17
_FILE_RE = re.compile(r"^(\d{2,})_.+\.sql$")

_CREATE_TABLE = """
create table if not exists public.schema_migrations (
  version    text primary key,
  applied_at timestamptz not null default now()
)
"""


def migration_files(directory: Path = MIGRATIONS_DIR) -> list[tuple[int, str, Path]]:
    """[(numero, versione, percorso)] in ordine numerico."""
    out = []
    for path in directory.glob("*.sql"):
        match = _FILE_RE.match(path.name)
        if match:
            out.append((int(match.group(1)), path.stem, path))
    return sorted(out)


def _pool():
    from backend.core.database import _get_pool  # noqa: PLC0415

    return _get_pool()


def status() -> dict[str, list[str]]:
    """{applied: [...], pending: [...]} senza applicare niente."""
    with _pool().connection() as conn:
        conn.execute(_CREATE_TABLE)
        applied = {r["version"] for r in conn.execute("select version from public.schema_migrations")}
    files = migration_files()
    if not applied:
        applied = {v for n, v, _ in files if n <= BASELINE_MAX}
    return {
        "applied": [v for _, v, _ in files if v in applied],
        "pending": [v for _, v, _ in files if v not in applied],
    }


def apply_pending() -> list[str]:
    """Applica le migrazioni mancanti; ritorna le versioni applicate ora."""
    files = migration_files()
    if not files:
        logger.warning("Migrazioni: nessun file in %s", MIGRATIONS_DIR)
        return []
    with _pool().connection() as conn:
        conn.execute(_CREATE_TABLE)
        applied = {r["version"] for r in conn.execute("select version from public.schema_migrations")}
        if not applied:
            # Primo avvio del runner: lo storico Supabase è già in init.sql.
            for n, version, _ in files:
                if n <= BASELINE_MAX:
                    conn.execute(
                        "insert into public.schema_migrations (version) values (%s) "
                        "on conflict do nothing",
                        (version,),
                    )
            applied = {v for n, v, _ in files if n <= BASELINE_MAX}
            logger.info("Migrazioni: baseline registrata (%d file storici)", len(applied))

    done: list[str] = []
    for _, version, path in files:
        if version in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        try:
            # Una transazione per migrazione: o tutta o niente.
            with _pool().connection() as conn:
                conn.execute(sql)
                conn.execute(
                    "insert into public.schema_migrations (version) values (%s)", (version,)
                )
        except Exception:
            logger.exception("Migrazione %s FALLITA: le successive non sono applicate", version)
            break
        logger.info("Migrazione applicata: %s", version)
        done.append(version)
    return done
