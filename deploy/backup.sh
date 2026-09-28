#!/bin/sh
set -eu

cd "$(dirname "$0")/.."
backup_dir="${BACKUP_DIR:-./deploy/backups}"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$backup_dir/meeting_rooms_$stamp.dump.partial"
finished="$backup_dir/meeting_rooms_$stamp.dump"
trap 'rm -f "$temporary"' EXIT
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$temporary"
docker compose -f compose.prod.yaml exec -T db pg_restore --list < "$temporary" > /dev/null
chmod 600 "$temporary"
mv "$temporary" "$finished"
trap - EXIT
printf 'Backup written: %s\n' "$finished"
