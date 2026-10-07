#!/bin/sh
set -eu
umask 077

cd "$(dirname "$0")/.."
backup_dir="${BACKUP_DIR:-./deploy/backups}"
env_file="${ENV_FILE:-.env}"
compose_file="${COMPOSE_FILE:-compose.prod.yaml}"
mkdir -p "$backup_dir"
chmod 700 "$backup_dir"
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
temporary="$(mktemp "$backup_dir/meeting_rooms_$stamp.XXXXXX.dump.partial")"
finished="${temporary%.partial}"
trap 'rm -f "$temporary"' EXIT
docker compose --env-file "$env_file" -f "$compose_file" exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > "$temporary"
docker compose --env-file "$env_file" -f "$compose_file" exec -T db pg_restore --list < "$temporary" > /dev/null
chmod 600 "$temporary"
mv "$temporary" "$finished"
trap - EXIT
printf 'Backup written: %s\n' "$finished"
