#!/usr/bin/env bash
# Ripristina un dump (formato custom, da dump_supabase.sh o backup_db.sh) in
# QUALSIASI Postgres di destinazione: quello locale del docker-compose (per
# consultare i dati sul Mac) o quello del VPS in produzione — stesso comando,
# cambia solo l'URL di destinazione.
#
#   ./scripts/restore_db.sh <dump_file> "<DATABASE_URL_destinazione>"
#
# Esempi:
#   # Verso il Postgres locale di docker-compose (deve già essere su):
#   docker compose up -d db
#   ./scripts/restore_db.sh backups/supabase_backup_20260720.dump \
#     "postgresql://postgres:postgres@host.docker.internal:5432/reseller"
#
#   # Verso il Postgres del VPS, lanciato DA SSH sul VPS stesso:
#   ./scripts/restore_db.sh backups/supabase_backup_20260720.dump \
#     "postgresql://postgres:<PASSWORD_VPS>@host.docker.internal:5432/reseller"
#
# NOTA: questo script esegue pg_restore DENTRO un container usa-e-getta, non
# sul tuo Mac/VPS direttamente — per questo l'host di destinazione è
# "host.docker.internal" (il Mac/server che ospita Docker) e NON "localhost"
# (che dentro il container userebbe punterebbe al container stesso).
#
# --clean --if-exists: sicuro da rilanciare più volte, ripulisce prima di
# riscrivere. --no-owner --no-privileges: Supabase usa ruoli che non esistono
# nel Postgres nuovo, li ignoriamo (il proprietario diventa chi si connette).
# --schema=public: un dump di Supabase include anche gli schemi interni
# auth/storage/realtime/vault (login, storage, ecc.) che il nostro backend
# non ha mai usato e che fallirebbero su un Postgres senza le estensioni di
# Supabase. Restringiamo al solo schema "public", dove vivono i nostri dati
# veri (opportunità, trend, target, deals...).
set -euo pipefail

DUMP_FILE="${1:?Uso: restore_db.sh <dump_file> <DATABASE_URL>}"
TARGET_URL="${2:?Uso: restore_db.sh <dump_file> <DATABASE_URL>}"

[ -f "$DUMP_FILE" ] || { echo "File non trovato: $DUMP_FILE"; exit 1; }

ABS_DIR="$(cd "$(dirname "$DUMP_FILE")" && pwd)"
BASENAME="$(basename "$DUMP_FILE")"

echo "Ripristino $DUMP_FILE → $TARGET_URL"
# postgres:17 per restare allineati alla versione di dump_supabase.sh/compose
# (evita incompatibilità di pg_restore contro un dump di versione diversa).
docker run --rm -v "$ABS_DIR":/dump --add-host=host.docker.internal:host-gateway \
  postgres:17-alpine \
  pg_restore --no-owner --no-privileges --clean --if-exists --schema=public -v \
  -d "$TARGET_URL" "/dump/$BASENAME"

echo
echo "Ripristino completato. Per consultare i dati:"
echo "  docker compose exec db psql -U postgres -d reseller"
echo "oppure con un client grafico (TablePlus/DBeaver) su localhost:5432"
echo "(da fuori Docker, sul Mac, si usa \"localhost\"; solo dentro un altro"
echo "container serve \"host.docker.internal\")."
