#!/bin/sh
set -eu

: "${POSTGRES_DB:?Set database name}"
: "${POSTGRES_USER:?Set database administrator}"
: "${POSTGRES_PASSWORD:?Set database administrator password}"
: "${POSTGRES_APP_USER:?Set distinct application role}"
: "${POSTGRES_APP_PASSWORD:?Set application password}"
if [ "$POSTGRES_APP_USER" = "$POSTGRES_USER" ]; then
    printf '%s\n' 'Application and database administrator roles must differ' >&2
    exit 1
fi
export PGPASSWORD="$POSTGRES_PASSWORD"
psql -h db -U "$POSTGRES_USER" -d "$POSTGRES_DB" --no-psqlrc --set=ON_ERROR_STOP=1 \
    --set=app_user="$POSTGRES_APP_USER" <<'SQL'
\getenv app_password POSTGRES_APP_PASSWORD
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT', :'app_user')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = :'app_user') \gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT PASSWORD %L', :'app_user', :'app_password') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'app_user') \gexec
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'app_user') \gexec
SELECT format('GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO %I', :'app_user') \gexec
SELECT format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO %I', :'app_user') \gexec
SELECT format('REVOKE UPDATE, DELETE, TRUNCATE ON TABLE audit_events FROM %I', :'app_user')
WHERE to_regclass('public.audit_events') IS NOT NULL \gexec
SQL
printf '%s\n' 'Application database role and current schema permissions prepared'
