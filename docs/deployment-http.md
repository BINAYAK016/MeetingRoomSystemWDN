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

Add real rooms through **Staff → Rooms**. No sample accounts or demo rooms are loaded. Review business hours, holidays, booking rules, and room capacities/facilities. Employee access supports `wdn.com.np` and `transgate.com.np`.

## 5. Verify from an office laptop

Open **`http://mbs.wdn.com.np/`** using the HTTP prefix. Verify employee email sign-in and logout, staff password/code sign-in, room search, and the booking lifecycle:

- Employee creates a pending request and the time slot is held.
- Staff approves the request; organizer receives the confirmation.
- Staff rejects another request with a visible reason; the slot becomes available.
- Employee edits an approved meeting; it returns to pending.
- Organizer cancels an eligible booking; the slot becomes available.
- Simultaneous requests for the same slot produce one reservation and one availability error.
- Check-in link works during the valid window; missed check-in releases the slot after the deadline.
- Reports, audit history, recurring dates, holiday rules, closures, and room deactivation work with real office data.

Check that company laptops can reach the office IP and resolve the domain. Do not expose port 80 to the public internet. Existing HTTPS rehearsal results in `verification-report.md` remain evidence for that profile; verify this actual server's DNS, mail, firewall, and restore procedure before rollout.

## Backups and updates

Take a backup using the matching HTTP Compose profile:

```sh
COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh
```

The script writes private custom-format dumps to `deploy/backups/` and checks their archive listings. Encrypt and copy backups to company-approved separate storage with retention; store `.env` separately in approved secret storage. Perform a restore drill into an isolated database rather than the live one. An archive listing alone does not prove restoration. The shared [backup and restore procedure](deployment.md#backup-and-restore) applies, substituting `compose.prod.http.yaml` for each Compose command.

For an update, first take and verify the backup, then use a maintenance window:

```sh
COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh
docker compose -f compose.prod.http.yaml stop proxy web worker
git pull --ff-only
docker compose -f compose.prod.http.yaml build --pull
docker compose -f compose.prod.http.yaml run --rm migrate
docker compose -f compose.prod.http.yaml run --rm db_setup
docker compose -f compose.prod.http.yaml up -d --wait --wait-timeout 180 web worker proxy
curl --fail --show-error http://mbs.wdn.com.np/healthz/
```

Preserve `.env`, the database credentials, Django secret, and PostgreSQL volume. Migration 0008 preserves legacy confirmed meetings as approved; reversing it cancels pending/rejected records, so review rollback/restore separately. Stop web/worker writers before any migration.

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
- Authentication email unavailable: review the relay host/port/sender and its authorization for this server's IP. SMTP-disabled mode intentionally denies mail-based sign-in.
- Database permission errors after an update: rerun committed migrations and `db_setup`; do not generate migrations on the server.

HTTP deliberately omits secure-cookie/HTTPS redirect/HSTS settings, so `check --deploy` can report transport warnings. Production-mode restrictions, CSRF checks, staff MFA, booking permissions, and database constraints remain active.
