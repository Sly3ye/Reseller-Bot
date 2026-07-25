#!/usr/bin/env bash
# Dump completo del database Supabase (formato custom, compresso) — il backup
# "punto zero" da fare SUBITO, prima di toccare/pausare/eliminare il progetto
# Supabase. Non installa nulla sul Mac: usa un container Docker usa-e-getta
# come client pg_dump.
#
#   ./scripts/dump_supabase.sh "<CONNECTION_STRING_SUPABASE>" [dir_destinazione]
#
# Dove trovare la connection string:
#   supabase.com → il tuo progetto → Project Settings → Database →
#   "Connection string" → scheda URI.
#
# IMPORTANTE: usa la connessione DIRETTA (porta 5432), NON il
# "Connection pooling" (porta 6543) — pg_dump non funziona bene attraverso
# il pooler PgBouncer in modalità transaction.
#
# Richiede Docker Desktop avviato.
set -euo pipefail

CONN="${1:?Uso: dump_supabase.sh \"<CONNECTION_STRING>\" [dir_destinazione]}"
DEST_DIR="${2:-./backups}"
mkdir -p "$DEST_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="supabase_backup_${STAMP}.dump"
ABS_DEST="$(cd "$DEST_DIR" && pwd)"

echo "Dump di Supabase → $DEST_DIR/$OUT"
# postgres:17 perché Supabase gira su Postgres 17: pg_dump si rifiuta di
# lavorare contro un server più recente del proprio (usa lo stesso major).
docker run --rm -v "$ABS_DEST":/dump postgres:17-alpine \
  pg_dump "$CONN" -F c -f "/dump/$OUT" -v

echo
echo "OK: $DEST_DIR/$OUT ($(du -h "$ABS_DEST/$OUT" | cut -f1))"
echo "Conserva questo file con cura (è l'intero database): copialo anche su"
echo "un secondo posto (SSD esterno, cloud) oltre a questo Mac."
echo
echo "Per consultarlo/ripristinarlo:"
echo "  docker compose up -d db"
echo "  ./scripts/restore_db.sh \"$DEST_DIR/$OUT\" \"postgresql://postgres:postgres@host.docker.internal:5432/reseller\""
