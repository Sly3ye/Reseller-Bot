#!/usr/bin/env bash
# Backup del database: pg_dump compresso dal container Postgres di compose.
#
#   ./scripts/backup_db.sh            # scrive in ./backups/reseller_<timestamp>.sql.gz
#   ./scripts/backup_db.sh /path/dir  # directory di destinazione custom
#
# Da mettere in cron sul VPS (es. ogni notte):
#   0 5 * * *  cd /opt/reseller-bot && ./scripts/backup_db.sh >> backup.log 2>&1
#
# Le IMMAGINI stanno nel volume docker `media`: per un backup completo copia
# anche quelle (es. rsync del volume, o `docker run --rm -v reseller-bot_media...`).
set -euo pipefail

DEST_DIR="${1:-./backups}"
RETENTION_DAYS="${BACKUP_RETENTION_DAYS:-14}"
mkdir -p "$DEST_DIR"

STAMP="$(date +%Y%m%d_%H%M%S)"
OUT="$DEST_DIR/reseller_${STAMP}.sql.gz"

echo "Backup → $OUT"
docker compose exec -T db pg_dump -U postgres -d reseller | gzip > "$OUT"
echo "OK ($(du -h "$OUT" | cut -f1))"

# Ruota i backup più vecchi di RETENTION_DAYS giorni.
find "$DEST_DIR" -name 'reseller_*.sql.gz' -mtime "+${RETENTION_DAYS}" -delete 2>/dev/null || true
echo "Backup più vecchi di ${RETENTION_DAYS} giorni rimossi."
