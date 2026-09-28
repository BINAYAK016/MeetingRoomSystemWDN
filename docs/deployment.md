# Private-network deployment

This guide is for the IT-provided Linux server. Keep the site reachable only from the approved company network or VPN. Use an internal DNS name that resolves to the server, with a certificate trusted by company devices.

## Before starting

Install Docker Engine and Docker Compose plugin. Give the deployment operator access to the GitHub repository. Permit outbound traffic to the company SMTP relay and inbound HTTPS only from the company network. Create the internal DNS record. Place the TLS certificate and private key at `deploy/certs/fullchain.pem` and `deploy/certs/privkey.pem`; keep the key readable only by the deployment operator and Docker, and never commit it. Confirm the SMTP relay accepts the chosen sender address.

Copy `.env.example` to `.env` on the server. Generate long independent random `POSTGRES_PASSWORD` and `DJANGO_SECRET_KEY` values. Set `DJANGO_ALLOWED_HOSTS` to the single internal hostname (without a scheme or port), `DJANGO_PUBLIC_BASE_URL` to its `https://` URL, `DJANGO_EMAIL_BACKEND=smtp`, `DJANGO_FROM_EMAIL`, and the SMTP settings. The production Compose file forces HTTPS, the WDN domain, and SMTP regardless of local defaults. Protect `.env` with mode 600.

## First deployment

```sh
git clone https://github.com/BINAYAK016/MeetingRoomSystemWDN.git
cd MeetingRoomSystemWDN
cp .env.example .env
# Fill .env and deploy/certs/fullchain.pem plus deploy/certs/privkey.pem.
chmod 600 .env deploy/certs/privkey.pem
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml build
docker compose -f compose.prod.yaml up -d db
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml up -d web worker proxy
curl --fail https://YOUR-INTERNAL-HOST/healthz/
```

Do not load the demo room fixture in production. Staff can enter actual rooms and facilities through the staff desk. Create each initial staff account only after SMTP works:

```sh
docker compose -f compose.prod.yaml exec web python manage.py create_staff_account person@wdn.com.np
```

The command emails a password setup link. The person sets a password, then signs in with that password and a one-time email code. Front Desk and Administrators can add other staff and employees from **People and access**. Test employee sign-in, staff sign-in, booking creation, overlap rejection, reminder delivery, check-in, automatic no-show, and Excel download on the private site before office rollout.

## Update

Take a backup first. Then:

```sh
git pull --ff-only
docker compose -f compose.prod.yaml build
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml up -d web worker proxy
curl --fail https://YOUR-INTERNAL-HOST/healthz/
```

Use the same `DJANGO_SECRET_KEY` and PostgreSQL volume across updates. Review migrations and the backup before applying an update.

## Backup and restore

`sh deploy/backup.sh` creates a PostgreSQL custom-format dump in `deploy/backups/` and checks its archive listing. Schedule it on the Linux host, for example daily with systemd timer or cron. Copy encrypted backups to company-approved separate storage, set retention under company policy, and test restore into an isolated database. A backup on the same server alone is insufficient against server failure. Keep backups private because they contain employee and meeting information.

Example isolated restore drill, after creating an empty test database named `meeting_rooms_restore` within the db container:

```sh
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" createdb -U "$POSTGRES_USER" meeting_rooms_restore'
docker compose -f compose.prod.yaml exec -T db sh -c 'PGPASSWORD="$POSTGRES_PASSWORD" pg_restore -U "$POSTGRES_USER" -d meeting_rooms_restore --no-owner --no-privileges' < deploy/backups/SELECTED.dump
```

Do not restore into the live database during a drill. Document the last successful restore and monitor disk space.

## Operational checks

`docker compose -f compose.prod.yaml ps` should show healthy PostgreSQL and running web, worker, and proxy. `docker compose -f compose.prod.yaml logs --tail=100 worker` shows worker errors. `curl --fail https://YOUR-INTERNAL-HOST/healthz/` confirms database reachability through the proxy. Staff should review failed email counts and audit history daily during the pilot. Use the company's existing monitoring for server disk, certificates, backups, and service restarts.
