#!/bin/sh
# Backup automatico (servizio `backup` del docker-compose): gira in un
# container postgres:17-alpine, quindi uguale su PC, Mac e VPS, senza cron.
#
# Ogni giro:
#   1. pg_dump (formato custom, quello che legge scripts/restore_db.sh) in
#      /backups/db/reseller_<data>.dump;
#   2. VERIFICA: lo ripristina in un DB temporaneo (reseller_verify) e
#      confronta i conteggi delle tabelle principali con l'originale — un
#      backup mai provato non è un backup;
#   3. foto: copia speculare in /backups/media (solo i file nuovi: le foto non
#      cambiano mai, non serve un archivio da 1+ GB a notte);
#   4. scrive l'esito in /backups/last_backup.json (lo leggono il cruscotto e
#      l'allarme del backend) e ruota i dump più vecchi di
#      BACKUP_RETENTION_DAYS (default 14).
#
# Quando: all'ora BACKUP_HOUR (default 5, dopo Motore Notturno e Garbage
# Collector), oppure appena possibile se l'ultimo backup riuscito ha più di 26
# ore (PC spento di notte). BACKUP_NOW=1 → un giro subito ed esce.
set -u

HOUR="${BACKUP_HOUR:-5}"
KEEP="${BACKUP_RETENTION_DAYS:-14}"
DIR=/backups
STATUS="$DIR/last_backup.json"
LAST_OK="$DIR/.last_ok_epoch"
TABLES="live_opportunities_tech live_opportunities_auto target_models deals market_trends price_history app_settings"

export PGHOST="${PGHOST:-db}" PGUSER="${PGUSER:-postgres}"
mkdir -p "$DIR/db" "$DIR/media"

count() {  # count <db> <tabella> → numero, o -1 se la tabella non c'è
  psql -d "$1" -Atc "select count(*) from public.$2" 2>/dev/null || echo -1
}

json_escape() { printf '%s' "$1" | tr '\n"\\' "   " | cut -c1-300; }

run_once() {
  started=$(date -Iseconds)
  stamp=$(date +%Y%m%d_%H%M)
  out="$DIR/db/reseller_$stamp.dump"
  err=""
  tables_json=""

  if pg_dump -Fc -d reseller -f "$out.part" 2>"$DIR/.err"; then
    mv "$out.part" "$out"
  else
    err="pg_dump fallito: $(tail -c 250 "$DIR/.err")"
    rm -f "$out.part"
  fi

  if [ -z "$err" ]; then
    dropdb --if-exists reseller_verify 2>/dev/null
    if createdb reseller_verify 2>"$DIR/.err" \
       && pg_restore --no-owner --no-privileges -d reseller_verify "$out" 2>"$DIR/.err"; then
      for t in $TABLES; do
        src=$(count reseller "$t")
        dst=$(count reseller_verify "$t")
        tables_json="$tables_json\"$t\":{\"live\":$src,\"restored\":$dst},"
        # Il dump è una fotografia: nel frattempo il DB vivo può crescere un
        # po'. Fallisce se manca la tabella o se ne manca più dell'1%.
        if [ "$src" -ge 0 ] && { [ "$dst" -lt 0 ] || [ $((dst * 100)) -lt $((src * 99)) ]; }; then
          err="verifica: $t ha $dst righe ripristinate contro $src"
        fi
      done
    else
      err="ripristino di prova fallito: $(tail -c 250 "$DIR/.err")"
    fi
    dropdb --if-exists reseller_verify 2>/dev/null
  fi

  media_src=-1
  media_dst=-1
  if [ -d /media ]; then
    # Solo i file che mancano (il "cp -n" di BusyBox salta intere cartelle
    # se esistono già, quindi niente copia ricorsiva).
    (cd /media && find . -type d -exec mkdir -p "$DIR/media/{}" \; \
      && find . -type f | while IFS= read -r f; do
           [ -e "$DIR/media/$f" ] || cp -p "$f" "$DIR/media/$f" || exit 1
         done) 2>"$DIR/.err" || err="${err:+$err; }foto: $(tail -c 200 "$DIR/.err")"
    media_src=$(find /media -type f | wc -l)
    media_dst=$(find "$DIR/media" -type f | wc -l)
    [ "$media_dst" -lt "$media_src" ] && err="${err:+$err; }foto: $media_dst copiate su $media_src"
  fi

  [ -z "$err" ] && date +%s > "$LAST_OK"
  find "$DIR/db" -name 'reseller_*.dump' -mtime "+$KEEP" -delete 2>/dev/null
  size=$( [ -f "$out" ] && du -k "$out" | cut -f1 || echo 0)

  ok=true
  [ -n "$err" ] && ok=false
  cat > "$STATUS.tmp" <<EOF
{"at":"$started","finishedAt":"$(date -Iseconds)","ok":$ok,"error":"$(json_escape "$err")",
 "file":"$(basename "$out")","sizeKb":$size,"retentionDays":$KEEP,
 "tables":{${tables_json%,}},
 "media":{"files":$media_src,"mirrored":$media_dst},
 "lastOkEpoch":$(cat "$LAST_OK" 2>/dev/null || echo null)}
EOF
  mv "$STATUS.tmp" "$STATUS"
  echo "$(date -Iseconds) backup ok=$ok ${err:+($err)}"
}

if [ "${BACKUP_NOW:-0}" = "1" ]; then
  run_once
  exit 0
fi

echo "Servizio backup: ogni giorno alle $HOUR:00 ($TZ), o subito se l'ultimo ha più di 26h."
while true; do
  now=$(date +%s)
  last=$(cat "$LAST_OK" 2>/dev/null || echo 0)
  today=$(date +%Y%m%d)
  done_today=$(find "$DIR/db" -name "reseller_${today}_*.dump" | head -1)
  if [ $((now - last)) -gt 93600 ] \
     || { [ "$(date +%H)" -eq "$HOUR" ] && [ -z "$done_today" ]; }; then
    run_once
  fi
  sleep 600
done
