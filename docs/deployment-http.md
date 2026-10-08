# Private-network HTTP deployment

**Transgate Tech | Binayak Bhandari**

This is the selected installation for **`http://mbs.wdn.com.np`**, on **Oracle Linux 9.8 x86_64**. It uses `compose.prod.http.yaml`, port 80, and no certificate or private CA. Browsers show **Not secure** because browser traffic is unencrypted. Keep access on the company network/VPN.

Production mode is independent of HTTPS: both production profiles disable the development email inbox and demo seeding, require generated secrets, and use the restricted PostgreSQL application role. Employee email links and staff email codes still require the real SMTP relay.

## Before starting

Run the following commands on the Linux server as `root`. Git, Docker Engine, and the Compose plugin have already been installed and verified. For another server, install those prerequisites first. Use the same repository directory and Compose project on every update to preserve the database volume.

Internal DNS must resolve `mbs.wdn.com.np` to this server's confirmed office interface IP, **`192.168.50.222`**. Confirm the interface and DNS result:

```sh
ip -brief address
getent hosts mbs.wdn.com.np
```

Set `HTTP_BIND_IP=192.168.50.222`. The Docker bridge address `172.17.0.1` is not the office interface. The profile requires an explicit bind address, so it will not silently publish port 80 on all interfaces.

Port 80 must be free. Permit it only from the approved office network/VPN using IT's network and firewall policy. Keep SELinux enabled. The HTTP profile labels its application-specific configuration mounts for SELinux; there is no need to disable SELinux or firewalld.

The default Docker subnet is `172.29.16.0/28`. If it overlaps an office route or another Docker network, adjust `PROXY_NETWORK_SUBNET`, `PROXY_NETWORK_DYNAMIC_RANGE`, `PROXY_IP`, and `AUTH_TRUSTED_PROXY_CIDRS` together. The fixed proxy address must remain inside the subnet and outside the automatic address range. Only that proxy address may supply trusted client-IP headers. Web and PostgreSQL expose no host ports.

## 1. Get the HTTP deployment files

For the already cloned server:

```sh
cd /opt/mbs/MeetingRoomSystemWDN
git switch mbs-prod
git pull --ff-only
```

For a fresh directory instead:

```sh
mkdir -p /opt/mbs
cd /opt/mbs
git clone --branch mbs-prod https://github.com/BINAYAK016/MeetingRoomSystemWDN.git
cd MeetingRoomSystemWDN
```

Do not run the HTTP and HTTPS profiles simultaneously for this installation. If services already exist, use the update section and take a backup before changing their configuration.

## 2. Configure the domain, binding, and SMTP

```sh
dnf install -y python3 nano
python3 deploy/create-env.py --production --http
```

The generator creates independent passwords and a Django secret, writes `.env` with private permissions, and refuses to replace an existing file. If `.env` already exists from the earlier HTTPS preparation, preserve its generated passwords and secret and edit that same file:

```sh
nano .env
```

Set these values:

```ini
DJANGO_PRODUCTION=true
DJANGO_HTTPS=false
DJANGO_ALLOWED_HOSTS=mbs.wdn.com.np
DJANGO_PUBLIC_BASE_URL=http://mbs.wdn.com.np
HTTP_BIND_IP=192.168.50.222
EMPLOYEE_EMAIL_DOMAINS=wdn.com.np,transgate.com.np

DJANGO_EMAIL_BACKEND=smtp
DJANGO_FROM_EMAIL=mbs@wdn.com.np
SMTP_HOST=maildc01.wdn.com.np
SMTP_PORT=25
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_TLS=false
SMTP_USE_SSL=false
```

These SMTP values are the previously working relay configuration. The new server's source IP must also be allowed by the relay. Relay acceptance and actual mailbox delivery are verified below.

In nano, save with **Ctrl+O**, **Enter**, then exit with **Ctrl+X**. Keep all generated `POSTGRES_*` passwords and `DJANGO_SECRET_KEY`. The database administrator and application role must be different users; preserve the existing administrator credentials if the PostgreSQL volume already contains data.

```sh
chmod 600 .env
docker compose -f compose.prod.http.yaml config --quiet
```

Use `config --quiet` for validation; plain `config` prints expanded configuration including passwords. If SMTP is not ready, use `DJANGO_EMAIL_BACKEND=disabled` temporarily. The app can start, but sign-in email delivery is unavailable; file-email mode is rejected in production.

## 3. Build, migrate, and start

Stop if a command fails:

```sh
docker compose -f compose.prod.http.yaml build --pull
docker compose -f compose.prod.http.yaml up -d db
docker compose -f compose.prod.http.yaml run --rm migrate
docker compose -f compose.prod.http.yaml run --rm db_setup
docker compose -f compose.prod.http.yaml up -d --wait --wait-timeout 180 web worker proxy
docker compose -f compose.prod.http.yaml ps
curl --fail --show-error http://mbs.wdn.com.np/healthz/
```

The worker establishes a heartbeat before web and proxy readiness succeed. `migrate` creates the complete schema, default booking policy, and PostgreSQL overlap protection. `db_setup` creates/updates the restricted application role and grants access to current tables/sequences. Run it after every migration. Migrations and backups use database administrator credentials; application web/worker services use the restricted runtime role.

If internal DNS is not ready yet, check from the server using the configured office IP and correct Host header:

```sh
curl --fail --show-error -H 'Host: mbs.wdn.com.np' http://192.168.50.222/healthz/
```

Resolve DNS before testing email sign-in links or opening the site to employees.

## 4. Verify mail and create staff access

This sends one SMTP test email:

```sh
docker compose -f compose.prod.http.yaml exec web python manage.py shell -c "from booking.services.mail_delivery import deliver_mail; print('Accepted by relay:', deliver_mail('MBS server SMTP test', 'Test email from the deployed MBS server.', ['binayak.bhandari@wdn.com.np']))"
```

Expected result: `Accepted by relay: 1`. Confirm the email actually arrives before creating staff access. If the relay rejects the sender or connection, ask IT to authorize this server's IP for the approved sender; keep passwords out of terminal output.

```sh
docker compose -f compose.prod.http.yaml exec web python manage.py create_staff_account binayak.bhandari@wdn.com.np
```

Open the emailed password setup link, set a password, then visit **`http://mbs.wdn.com.np/staff/sign-in/`**. Staff sign-in requires the password plus an emailed code. Repeat the account command for each approved Front Desk/Administrator user. If email setup fails, fix the relay and rerun it for the same address; it does not create duplicate accounts.

Add real rooms through **Staff desk → Rooms → Add room**, including an optional supported photo. No sample accounts or demo rooms are loaded. Review business hours, holidays, booking rules, room capacities/facilities and each room's **Requires approval** setting (checked by default). Employee access supports `wdn.com.np` and `transgate.com.np`.

## 5. Verify from an office laptop

Open **`http://mbs.wdn.com.np/`** using the HTTP prefix. Verify employee email sign-in and logout, staff password/code sign-in, room search, and the booking lifecycle:

- In a checked Requires approval room, employee creates a Pending request and the time slot is held.
- Staff approves the request; organizer receives the confirmation.
- Staff rejects another request with a visible reason; the slot becomes available.
- Employee substantively edits an Approved meeting in a checked room; it returns to Pending.
- Uncheck another room in Staff desk → Rooms, verify the saved/audited setting, then submit a valid employee booking there; it starts Approved and queues confirmation/check-in immediately.
- Toggle a room containing an existing Pending request: its status stays Pending, and an unchanged edit stays Pending. A substantive valid edit in an unchecked room becomes Approved.
- Organizer cancels an eligible booking; the slot becomes available.
- Simultaneous requests for the same slot produce one reservation and one availability error.
- Branded HTML and plain-text authentication/meeting emails arrive and remain usable in company mail clients. Organizer Check in opens browser confirmation and works during the valid window; a preview performs no action and attendee emails contain no organizer token. Missed check-in releases the slot after the deadline.
- A saved attendee signs in and sees the meeting in My meetings, overview/calendar and read-only detail. Role/status/search filters work; unrelated employees cannot read details. Attendee edit/cancel is denied and removal ends access.
- Typing two letters in Attendees offers up to eight registered active company accounts with mouse/keyboard selection; manual external addresses remain valid.
- Three-step booking, attendee headcount, Internal + External guest company, all-occurrence availability and native form fallback work.
- Reports, audit history, recurring dates, holiday rules, closures, and room deactivation work with real office data.
- Optional staff-uploaded room photos display only while authenticated, survive recreation, and restore from the matching media archive.
- Booking/profile/People department dropdowns contain the eight initial options and imported legacy names. Verified staff can add or deactivate an option through Departments; existing booking labels remain intact.

Check that company laptops can reach the office IP and resolve the domain. Do not expose port 80 to the public internet. Existing HTTPS rehearsal results in `verification-report.md` remain evidence for that profile; verify this actual server's DNS, mail, firewall, and restore procedure before rollout.

The department update adds migration `0012_department` and requires the full update procedure below, including `migrate` and `db_setup` for the new catalog table/sequence. The earlier calendar redesign, invited-meeting, attendee-suggestion and professional-email updates added no migration beyond 0011. Rebuild and recreate both web and worker to load current code/templates; preserve database, media, `.env` and existing settings. No new environment variable is needed.

## Backups and updates

Take a backup using the matching HTTP Compose profile:

```sh
COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh
```

The script writes private custom-format database dumps to `deploy/backups/` and checks their archive listings. It does **not** include optional room photos. Web stores those in the named `room_media` volume at `/app/media`; back up/restore a matching photo archive using [Room photo backup and recovery](operations-runbook.md#room-photo-backup-and-recovery). Ordinary container recreation preserves the volume. Encrypt and copy backups to company-approved separate storage with retention; store `.env` separately in approved secret storage. Perform a restore drill into an isolated database rather than the live one. An archive listing alone does not prove restoration. The shared [backup and restore procedure](deployment.md#backup-and-restore) applies, substituting `compose.prod.http.yaml` for each Compose command.

For an update, build the current branch before the outage, then stop writers and take a matching database/media recovery point while PostgreSQL remains running. Execute this from the installed repository; if its checked branch or clean-worktree gate fails, preserve the local changes and investigate before continuing. The subshell stops on any failure:

```bash
(
set -eu
cd /opt/mbs/MeetingRoomSystemWDN
mbs() { docker compose -f compose.prod.http.yaml "$@"; }

test "$(git branch --show-current)" = "mbs-prod"
if [ -n "$(git status --porcelain)" ]; then
  echo "Local code changes found. Stop here and inspect git status --short."
  exit 1
fi

git pull --ff-only origin mbs-prod
mbs config --quiet
mbs build web
mbs up -d --wait --wait-timeout 90 db
mbs run --rm --no-deps -T --entrypoint sh web -c 'test -w /app/media/rooms/photos'

mbs stop proxy web worker
COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh
umask 077
mbs_media_backup="deploy/backups/room_media_$(date -u +%Y%m%dT%H%M%SZ).tar.gz"
mbs run --rm --no-deps -T --entrypoint sh web -c 'tar -C /app/media -czf - .' > "$mbs_media_backup"
tar -tzf "$mbs_media_backup" > /dev/null

mbs run --rm --no-deps migrate
mbs run --rm --no-deps db_setup
mbs up -d --no-deps --force-recreate --wait --wait-timeout 180 web worker proxy
mbs exec -T web python manage.py check
mbs exec -T web python manage.py showmigrations booking
mbs ps
curl --fail --show-error --resolve mbs.wdn.com.np:80:192.168.50.222 http://mbs.wdn.com.np/healthz/
git log -1 --oneline
)
```

Keep the printed database dump, media archive and release commit together as one recovery point and copy them to approved separate storage. Archive listing validates structure, not a successful restore. If a command fails after services were stopped, leave the writers stopped, inspect the failure and use the recovery runbook before resuming; do not delete volumes or start old code against a newer schema.

Preserve `.env`, the database credentials, Django secret, PostgreSQL volume and `room_media` photo volume. For an installation with photos, stop writers and take the paired database/photo backup before updating. This release requires the complete committed migration chain through `0012_department`; it preserves existing records, and no room reseeding is required. Migration 0011 checks Requires approval for existing rooms without changing saved booking statuses. Migration 0012 adds the eight requested departments and imports existing nonblank user/booking labels without rewriting their saved strings. Verify all applied using `docker compose -f compose.prod.http.yaml exec web python manage.py showmigrations booking`; then inspect **Staff desk → Departments**. Migration 0008 preserves legacy confirmed meetings as approved; reversing it cancels pending/rejected records, so review rollback/restore separately. Stop web/worker writers before any migration.

Stop containers while preserving the database:

```sh
docker compose -f compose.prod.http.yaml down
```

Never add `--volumes` unless intentionally deleting production data.

## Troubleshooting and monitoring

```sh
docker compose -f compose.prod.http.yaml ps
docker compose -f compose.prod.http.yaml logs --tail=100 web worker proxy db
```

`/livez/` reports the web process. `/healthz/` also requires PostgreSQL and a recent worker heartbeat. Docker restart policies restart exited processes; IT must monitor unhealthy containers, failed mail, backups, and disk usage.

- Connection refused: check `HTTP_BIND_IP`, port conflicts, container health, and the office firewall rule.
- Permission denied on a bind mount with SELinux enforcing: check the HTTP profile's `:Z` labels, file ownership, and audit logs; keep SELinux enforcing.
- Sign-in links point to HTTPS: correct `.env` to `DJANGO_PUBLIC_BASE_URL=http://mbs.wdn.com.np`, recreate web/worker, then request a new email.
- Browser automatically changes HTTP to HTTPS: an earlier HTTPS test may have stored HSTS for this hostname. Remove that saved host policy on the affected test device or have IT arrange its expiry; the HTTP proxy does not send HSTS.
- Session-check/CSRF page: load a fresh form at the same HTTP hostname, confirm cookies are enabled, and use the latest image. The response must use `Referrer-Policy: same-origin`; `no-referrer` makes native browser POSTs send Origin null. After reproducing, `docker compose -f compose.prod.http.yaml logs --since 5m --tail=80 web` records a safe category (`missing_session`, `missing_token`, `invalid_token`, `origin_mismatch`, `referer_rejected`, or `other`) and request reference. Do not disable CSRF or trust null origins.
- Authentication email unavailable: review the relay host/port/sender and its authorization for this server's IP. SMTP-disabled mode intentionally denies mail-based sign-in.
- Database permission errors after an update: rerun committed migrations and `db_setup`; do not generate migrations on the server.

HTTP deliberately omits secure-cookie/HTTPS redirect/HSTS settings, so `check --deploy` can report transport warnings. Production-mode restrictions, CSRF checks, staff MFA, booking permissions, and database constraints remain active.
