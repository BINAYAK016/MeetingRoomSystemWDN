# Private-network HTTPS deployment

**Transgate Tech | Binayak Bhandari**

This guide uses `compose.prod.yaml` for HTTPS with a certificate trusted by company devices. The selected office HTTP installation at `http://mbs.wdn.com.np` instead uses the [private-network HTTP guide](deployment-http.md) and `compose.prod.http.yaml`; it requires no certificate. Run one production profile for a given installation.

For HTTPS, use the IT-provided Linux server, an internal DNS name, and a trusted certificate. Restrict inbound HTTPS to the approved company network/VPN. The application can start with email disabled; employee/staff mailbox verification requires IT's SMTP configuration before rollout.

## Prepare configuration

Install Docker Engine, the Docker Compose plugin, and Git. Give the deployment operator repository access. Create internal DNS and permit outbound access to the approved SMTP relay when configured. Place the certificate chain and key at `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem`; protect the key and never commit it. The certificate directory and backups are excluded from image builds.

```sh
git clone --branch mbs-prod https://github.com/BINAYAK016/MeetingRoomSystemWDN.git
cd MeetingRoomSystemWDN
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.12-slim python deploy/create-env.py --production
```

The generator creates independent secrets and refuses to overwrite existing configuration. Edit `.env`: set the internal hostname in `DJANGO_ALLOWED_HOSTS` and matching HTTPS origin in `DJANGO_PUBLIC_BASE_URL`. Set `POSTGRES_DB` and distinct database administrator/application role names. Preserve administrator credentials on an existing database volume; changing image initialization variables does not change existing database credentials. Protect `.env` and the certificate key with mode 600.

Production requires `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `DJANGO_PUBLIC_BASE_URL`. Keep `DJANGO_EMAIL_BACKEND=disabled` until the SMTP relay is ready. This HTTPS Compose profile forces `DJANGO_PRODUCTION=true` and `DJANGO_HTTPS=true`, and allows the `wdn.com.np` and `transgate.com.np` employee domains. File-email development mode is rejected in both production profiles.

The proxy has fixed Docker address `172.29.16.14` within `172.29.16.0/28`; only this address may supply client IP headers. Automatic addresses use `172.29.16.0/29`, so they cannot collide with the proxy. If the subnet conflicts with another network, change `PROXY_NETWORK_SUBNET`, `PROXY_NETWORK_DYNAMIC_RANGE`, `PROXY_IP`, and `AUTH_TRUSTED_PROXY_CIDRS` together. Keep the proxy outside the dynamic range and inside the subnet. The proxy overwrites `X-Real-IP`; web and PostgreSQL expose no host ports. Do not grant trust to arbitrary client networks.

## First deployment

```sh
chmod 600 .env deploy/certs/privkey.pem
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml build --pull
docker compose -f compose.prod.yaml up -d db
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml run --rm db_setup
docker compose -f compose.prod.yaml up -d web worker proxy
docker compose -f compose.prod.yaml ps
curl --fail https://YOUR-INTERNAL-HOST/healthz/
```

Migrations create the complete schema, `btree_gist` overlap protection, and default booking policy. `db_setup` creates/updates a separate `NOSUPERUSER`, `NOCREATEDB`, `NOCREATEROLE` runtime role and grants access to current application tables/sequences. Runtime has no schema creation permission and cannot update/delete audit history. Migrations and backups use the database administrator credentials. Run `db_setup` after every migration so newly added tables receive application permissions.

The web readiness check requires PostgreSQL and a successful worker cycle in the last two minutes. Give the initial worker a few seconds to establish its heartbeat. Proxy waits for web readiness before starting. HTTP 503 during startup is a readiness failure rather than a successful launch.

No sample accounts or demo rooms are loaded automatically. Enter real rooms, floor/location, capacities, equipment, descriptions, and instructions through staff controls. The local-only `seed_demo_rooms` command refuses production deployment and existing rooms. Staff add approved holidays and review booking rules after the first sign-in.

## Enable email and initial staff

Supply these `.env` values from IT:

| Variable | Required configuration |
| --- | --- |
| `DJANGO_EMAIL_BACKEND` | Set `smtp` after the relay is available. |
| `SMTP_HOST`, `SMTP_PORT` | Approved relay and port. |
| `DJANGO_FROM_EMAIL` | Approved sender address/name. |
| `SMTP_USER`, `SMTP_PASSWORD` | Required when the relay authenticates users; otherwise empty with IT-approved IP authorization. |
| `SMTP_USE_TLS` | `true` for STARTTLS, otherwise `false`. |
| `SMTP_USE_SSL` | `true` for implicit TLS, otherwise `false`; cannot be combined with STARTTLS. |

STARTTLS usually uses port 587; implicit TLS usually uses 465. An internal non-TLS relay is only appropriate when explicitly approved by IT. No relay username, password, or company credentials are stored in this repository.

```sh
docker compose -f compose.prod.yaml up -d --force-recreate web worker
docker compose -f compose.prod.yaml exec web python manage.py create_staff_account person@wdn.com.np
```

Repeat the staff command for each approved Front Desk/Administrator account. It emails a one-time password setup link; the person sets a password and signs in with their password plus email code. If mail is unavailable, the command fails with a clear error and records that staff access was enabled. Configure the relay and rerun the command for the same address; no duplicate account is created. Do not pass passwords or tokens on the command line.

SMTP-disabled startup logs a warning, denies email authentication, and leaves notification jobs pending without consuming retry attempts. Actual relay failures are recorded and retried up to five attempts; the booking remains saved. Backend acceptance is required before marking a notification sent. Obsolete reminders are superseded, and reminders that recover during the 15-minute check-in window remain usable. A retry after an ambiguous SMTP response can produce duplicate mail.

After fixing an outage that exhausted five attempts, requeue eligible failures with `docker compose -f compose.prod.yaml exec worker python manage.py retry_failed_mail --all`, or target one message with `--id NUMBER`. The command checks the current booking status, supersedes obsolete reminders/confirmations, resets retry state, and records an audit event. It never prints email bodies or secure links.

## Pilot verification

Check HTTPS certificate trust from a company laptop and employee company-email sign-in/logout. Verify staff password/code sign-in, profile, room creation/edit/deactivation/reactivation, real facilities and capacities, pending requests, approval/rejection/reason, booking change/cancellation, recurring dates, holiday/business rules, and calendar privacy. A simultaneous same-slot attempt must produce one booking and an availability error for the other user. Employees must receive no staff access by changing URLs.

Verify organizer/staff request and rejection notices, organizer/attendee/staff approval confirmation and change/cancellation notices, one-hour reminder, email check-in before the 15-minute deadline, automatic no-show release, manual staff check-in, closures, audit history, and Excel export. Verify failed mail remains visible and retries without losing the booking. Utilization reports use configured business hours and holidays for the selected range; historical policy/holiday changes can change the denominator, so treat utilization as an operational estimate rather than a payroll/accounting measurement.

The repository's automated tests and isolated deployment verification do not replace company-server checks for actual mail delivery, DNS, certificate trust, firewall/VPN access, backup storage, and representative load.

## Update

Take and verify a backup first. Plan a short maintenance window:

```sh
sh deploy/backup.sh
docker compose -f compose.prod.yaml stop proxy web worker
git pull --ff-only
docker compose -f compose.prod.yaml build --pull
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml run --rm db_setup
docker compose -f compose.prod.yaml up -d web worker proxy
curl --fail https://YOUR-INTERNAL-HOST/healthz/
```

Current updates apply `0009_mixed_meeting_type`, `0010_room_photo` and `0011_room_requires_approval` after the approval schema; they preserve existing records and do not reseed rooms. Migration 0011 defaults existing/new rooms to Requires approval checked and does not rewrite saved booking statuses. Staff may then choose each room's policy through Rooms; no new environment setting is required. Take paired database/photo backups for an installation with uploaded files, using [Room photo backup and recovery](operations-runbook.md#room-photo-backup-and-recovery) with the HTTPS Compose profile. Migration 0008 preserves existing confirmed meetings as approved and adds pending request occupancy. Reversing it cancels pending/rejected requests; use a reviewed rollback/restore plan. Stop all writers during migration, then reapply runtime grants.

Preserve the Django secret, database administrator credentials, PostgreSQL volume and `room_media` photo volume across updates. Review migrations before applying them; restore planning is required for schema rollback. Stop with `docker compose -f compose.prod.yaml down` to preserve database storage. Never use `down --volumes` on production unless intentionally destroying its data.

## Backup and restore

Optional room photos are stored in the persistent `room_media` Docker volume mounted at `/app/media` in web, for both HTTPS and HTTP production profiles. Staff upload real room photos through **Rooms → Add/Edit room**; supported JPEG/PNG/WebP files are limited to 5 MiB and 12 million pixels, converted to JPEG without supplied metadata, and served only to authenticated users. Existing rooms without photos remain valid. There is no public `/media/` file server.

The database dump does not contain photo files. Back up the `room_media` volume alongside the database, using company-approved Docker volume backup tooling and separate storage. Stop web during a paired database/media backup to avoid photo replacement during the copy. Preserve the original volume ownership (UID/GID 1000) on restore. Restore photos under `/app/media/rooms/photos` together with the database room records; recreating containers preserves the named volume, while `down --volumes` destroys it. Include photo upload, viewing and restoration in the restore drill. [Room photo backup and recovery](operations-runbook.md#room-photo-backup-and-recovery) provides archive/extraction commands; substitute `compose.prod.yaml` for the selected HTTP profile when operating this HTTPS installation.

`sh deploy/backup.sh` produces a custom-format PostgreSQL dump, verifies its archive listing, and writes private files in `deploy/backups/`. Schedule it on the Linux host; encrypt and copy backups to company-approved separate storage with retention under company policy. Monitor success and disk space. A same-server backup does not protect against server loss. Back up `.env` and TLS material separately in approved secret storage.

The script accepts `COMPOSE_FILE` (default `compose.prod.yaml`), `ENV_FILE` (default `.env`), and `BACKUP_DIR` overrides. HTTP installations use `COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh`. If using an explicitly named Compose project, pass the matching `COMPOSE_PROJECT_NAME` when backing up; the script must target the same project as the live services. Temporary dump filenames are unique and private, and incomplete dumps are removed on failure.

Restore drill into a new, isolated database:

```sh
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" createdb -U "$POSTGRES_USER" meeting_rooms_restore'
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d meeting_rooms_restore --exit-on-error --no-owner --no-privileges' < deploy/backups/SELECTED.dump
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" psql -U "$POSTGRES_USER" -d meeting_rooms_restore -c "SELECT COUNT(*) FROM reservations;"'
```

A successful archive listing alone does not prove restoration. Compare key record counts, room/booking history, and schema in the restored database; record the date and result. Never restore into the live database during a drill. For actual disaster recovery, stop web/worker, restore into an empty target, run `db_setup` for its runtime permissions, start services, and perform acceptance checks before reopening office access.

## Monitoring and troubleshooting

`/livez/` is web liveness. `/healthz/` is PostgreSQL plus worker readiness and exposes only dependency status. Docker health checks cover DB, web, worker, and proxy. Run `docker compose -f compose.prod.yaml logs --tail=100 web worker proxy db`. Restart policies restart exited processes; IT monitoring must alert on unhealthy containers, stale heartbeats, failed emails, missing backups, low disk, and expiring certificates.

The worker reconciles approximately every 30 seconds. It sends individual messages with a ten-second timeout between reconciliations, so slow SMTP can add up to one timeout to a scheduled cycle. A stale worker reports unhealthy after two minutes. Staff should monitor pending/failed email during the pilot and can check in bookings manually during the valid window.

If web reports a missing database table after an update, rerun committed migrations with the administrator service and then `db_setup`; do not generate migrations on the server. If runtime gets permission errors, review the application role name/password and the last successful `db_setup`. Existing PostgreSQL credentials are not changed by editing image environment defaults.

Production `python manage.py check --deploy` was verified with synthetic HTTPS configuration and disabled email. It reports two expected, unsilenced warnings: `security.W005` (HSTS does not include subdomains) and `security.W021` (HSTS preload is disabled). This application controls one internal hostname; enabling either policy could impose HTTPS requirements on company subdomains beyond the application's ownership. Keep these disabled unless IT explicitly approves a domain-wide HSTS policy. Secure cookies, HTTPS redirect, explicit allowed hosts, and the host's HSTS header remain enabled.

SMTP/email credentials must be supplied by the system administrator during production deployment. No production email credentials are included in this repository.
