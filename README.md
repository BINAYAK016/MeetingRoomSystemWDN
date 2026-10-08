# Meeting Booking System

**Transgate Tech | Binayak Bhandari**

An internal meeting room application for employees with `wdn.com.np` or `transgate.com.np` email addresses. Django renders the employee and staff interface; PostgreSQL stores records, sessions, notification jobs, and audit history. A worker sends email and reconciles reminders, completed meetings, and missed check-ins. Docker Compose runs the application, worker, and persistent PostgreSQL database; production adds an Nginx proxy on the company network. Separate deployment profiles support HTTPS and the explicitly selected private-network HTTP installation.

The interface uses the Transgate navy/red palette and logo, with Times New Roman as approved. Front Desk and Administrators have identical staff permissions. Staff use a password plus a company-email code; employees use a company-email link.

## Complete documentation

Start with the [documentation index](docs/index.md). Detailed guides cover all features and use cases, employee and staff tasks, server operations, backups/restoration, and troubleshooting with log/diagnostic commands. A printable [complete handbook](docs/MBS_Complete_Handbook.pdf) accompanies the Markdown guides. [Build instructions](docs/handbook-build.md) explain regeneration.

## Features

- Room search, details, capacity/facilities, optional staff-managed real photos, and a room-filtered Month/Week/Day calendar with private meeting cards, date navigation and available-start booking links.
- Three-step booking flow: Schedule & details → Attendees → Review & confirm, with real room availability for every selected recurring occurrence. Native form fallback keeps booking usable without JavaScript.
- Internal, External and Internal + External meetings; guest company is required for external/mixed meetings.
- Department dropdowns for bookings and profiles, with an active catalog managed by staff. Initial options are Accounts, Administrative, Logistics, Sales, Oracle Support, Dell Support, Toshiba and ATM support; existing department labels are also retained.
- Own bookings and profile; booking requests, modification, and cancellation.
- Per-room approval: checked **Requires approval** rooms create Pending employee requests; unchecked rooms confirm them immediately. Pending requests reserve the slot; staff approval confirms the meeting, rejection records a reason and releases the slot.
- Daily, weekly, and monthly recurrence within the two-week advance window. Later monthly dates are reserved manually.
- Business hours, holidays, meeting duration, time slots, and room gap enforced on the server. PostgreSQL exclusion constraints prevent conflicting concurrent reservations, including room closures.
- Verified staff can upload a company holiday `.xlsx` schedule, review new/updated/unchanged dates and existing meeting counts, then confirm an atomic import. A downloadable Date/Occasion template is available under Holidays; omitted dates and saved meetings remain intact.
- Request, approval, rejection, modification, cancellation, reminder, check-in, and no-show notifications for the organizer, attendees, and staff.
- Branded HTML and plain-text emails for authentication and meeting events, with clear schedule/details and relevant action buttons. Organizer-only **Check in** opens a secure browser confirmation; check-in opens at start and the worker releases missed check-ins after 15 minutes.
- **My meetings** includes organized and invited meetings with role/status/search filters and read-only attendee detail access. Attendee visibility also applies to dashboard/calendar; management remains organizer or verified staff only.
- Attendee autocomplete suggests up to eight active approved-domain employee accounts after two typed characters; external/manual addresses remain supported.
- Staff room management, closures, employee/access management, booking on behalf of employees, reasoned rule overrides, audit history, statistics, and Excel export.

Direct HCL/Outlook calendar integration remains a later phase. WDN third-floor senior-management priority is handled by Front Desk manually.

## Stack and requirements

Python 3.12, Django 5.2 LTS, PostgreSQL 17, Gunicorn, WhiteNoise, openpyxl, and Nginx. Install Docker Desktop with the Linux engine on a laptop, or Docker Engine plus the Compose plugin on a Linux server. Docker handles Python and application dependencies; a separate local Python installation is optional.

## Local setup

In PowerShell, from this repository, create a fresh `.env` with generated secrets:

```powershell
docker run --rm -v "${PWD}:/workspace" -w /workspace python:3.12-slim python deploy/create-env.py
docker compose build
docker compose up -d db
docker compose run --rm migrate
docker compose up -d web worker
Invoke-WebRequest http://127.0.0.1:8000/healthz/
```

The environment generator refuses to replace an existing `.env`. For an existing installation, preserve its database password and Django secret, review `.env.example` for new variables, then build and migrate. A fresh worker heartbeat may take a few seconds before readiness returns HTTP 200.

For an existing demo, back up its database first and stop both writers before migrating to `mbs-prod`. Do not run old demo code against the approval schema:

```powershell
git switch mbs-prod
git pull --ff-only
docker compose stop web worker
docker compose exec -T db sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc -f /tmp/pre-mbs-prod.dump'
docker compose cp db:/tmp/pre-mbs-prod.dump ./pre-mbs-prod.dump
docker compose build
docker compose run --rm migrate
docker compose up -d web worker
```

Protect the dump; backup archives are Git-ignored. Preserve `.env`, its database password, Django secret, database volume and optional `room_media` volume. A database dump does not contain uploaded photos: back up/restore that volume alongside the matching database snapshot. Existing confirmed meetings become approved. Current upgrades apply the complete committed migration chain through `0012_department`; they preserve existing rooms/bookings and do not seed rooms. Migration 0011 sets Requires approval to checked for existing rooms, preserving their review requirement. Migration 0012 adds the department dropdown catalog while preserving saved department strings. See [photo backup/recovery](docs/operations-runbook.md#room-photo-backup-and-recovery) before updating an installation with uploads.

Open <http://127.0.0.1:8000/>. Local `.env.example` explicitly selects `DJANGO_EMAIL_BACKEND=file`; messages are written to a Docker volume and appear in the development inbox at <http://127.0.0.1:8000/dev/mail/>. This local convenience does not verify mailbox ownership. It is unavailable in either production profile and must never be used for company rollout.

Optional demonstration rooms, only in an empty local directory:

```powershell
docker compose exec web python manage.py seed_demo_rooms
docker compose exec web python manage.py create_staff_account your.name@wdn.com.np
```

Open the staff setup link in the development inbox, set a password, and use `/staff/sign-in/`. Its email code appears in the same development inbox. Actual room data is entered through the staff interface.

Stop containers and preserve data with `docker compose down`. Restart with `docker compose up -d web worker`. Database, optional room photos (`room_media`) and local email persist in named volumes. Never add `--volumes` to the stop command unless intentionally deleting the data.

The department catalog requires migration `0012_department`. It creates the catalog, adds the eight initial options and imports existing nonblank profile/booking labels case-insensitively without rewriting their saved strings. Follow the normal maintenance procedure: back up, stop writers, apply committed migrations, reapply runtime permissions with `db_setup` in production, and recreate web/worker. Preserve database, media, `.env` and existing settings; no new environment variable is required. Earlier calendar, invited-meeting, attendee-suggestion and professional-email updates added no migration beyond 0011.

The holiday Excel upload adds no migration beyond `0012_department`, dependency, service or environment variable. Rebuild and recreate the application using the [HTTP update procedure](docs/deployment-http.md#backups-and-updates). Staff sign in with password plus email code, then use **Holidays → Download template / Upload Excel → Preview holidays → Confirm import**. See the [staff holiday workflow](docs/staff-guide.md#9-manage-company-holidays) for format rules and conflict review.

## Environment and email

`.env.example` describes local configuration. `.env.production.example` describes HTTPS deployment; `.env.production.http.example` describes private-network HTTP deployment. Actual `.env*` files, certificate keys, and backup archives are excluded from Git and Docker build contexts.

| Variable | Purpose |
| --- | --- |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Database name and bootstrap/migration administrator. Preserve these for existing volumes. |
| `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD` | Production application role with database data access and no superuser, role-creation, or database-creation privileges. |
| `DJANGO_SECRET_KEY` | Independent generated secret; production requires at least 50 characters. Preserve across updates. |
| `DJANGO_ALLOWED_HOSTS` | Allowed hostnames. Production proxy expects one internal hostname without scheme/port. |
| `DJANGO_PUBLIC_BASE_URL` | Matching origin used in email links, e.g. `https://meetings.company.invalid` or `http://mbs.wdn.com.np` for the selected HTTP profile. |
| `DJANGO_PRODUCTION` | Both production Compose profiles force `true`; development inbox and demo seeding remain disabled independently of transport. |
| `DJANGO_HTTPS` | Secure cookies and HTTPS redirect. `compose.prod.yaml` forces `true`; `compose.prod.http.yaml` forces `false`. |
| `HTTP_BIND_IP` | HTTP profile only: required server office-interface IP. For this installation, `192.168.50.222`. |
| `EMPLOYEE_EMAIL_DOMAINS` | Comma-separated local employee domains; defaults to `wdn.com.np,transgate.com.np`. Production allows these two domains. |
| `DJANGO_EMAIL_BACKEND` | `file` for local HTTP development, `disabled` while unconfigured, or `smtp` for the approved relay. |
| `AUTH_TRUSTED_PROXY_CIDRS` | Networks/IPs allowed to supply `X-Real-IP`; production trusts only its fixed proxy IP. |
| `PROXY_NETWORK_SUBNET`, `PROXY_NETWORK_DYNAMIC_RANGE`, `PROXY_IP` | Production proxy network; keep the fixed proxy outside the automatic address range and update the trusted CIDR consistently if changed. |

Example files intentionally omit relay credentials. The selected office configuration is documented in the HTTP installation/runbook: `maildc01.wdn.com.np:25`, sender `mbs@wdn.com.np`, no relay AUTH, TLS/SSL false. Disabled mode allows startup, logs a configuration warning, preserves queued notifications without consuming retries, and rejects sign-in email delivery. Selecting `smtp` without host/sender also disables delivery with a warning. No message is marked sent unless the backend accepts it. The local file mode records a message locally and performs no external delivery.

| SMTP variable | Deployment value |
| --- | --- |
| `SMTP_HOST` | Company SMTP relay hostname/IP. |
| `SMTP_PORT` | Approved relay port, commonly 587 for STARTTLS or 465 for implicit TLS. |
| `SMTP_USER`, `SMTP_PASSWORD` | Relay credentials if authentication is required; leave empty only when IT approves an IP-authorized relay. |
| `DJANGO_FROM_EMAIL` | Approved sender address/name. |
| `SMTP_USE_TLS` | `true` for STARTTLS. |
| `SMTP_USE_SSL` | `true` for implicit TLS; never enable simultaneously with STARTTLS. |

After supplying these, set `DJANGO_EMAIL_BACKEND=smtp` and recreate web/worker. Synchronous employee/staff authentication reports unavailable delivery without granting a session. Notification failures keep bookings intact, retry up to five attempts, and remain visible to staff. SMTP delivery acceptance does not guarantee inbox arrival; IT verifies relay and mailbox behavior during pilot testing. An ambiguous SMTP result may cause duplicate delivery after a retry.

## Verification and builds

```powershell
docker compose build
docker compose run --rm test
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
```

Tests require PostgreSQL and cover email configuration/failure, secure authentication, authorization, room management, booking changes, concurrent conflicts, recurrence, check-in, worker health, and page rendering. The test runner creates and destroys a separate test database; use local configuration rather than production credentials.

Development tools in `requirements-dev.txt` provide `ruff check .` and `ruff format --check .`; CI runs these alongside PostgreSQL tests, migration checks, Django checks, and the Docker build. Python syntax can also be checked with `python -m compileall -q booking config`. No separate static type checker is configured for this Django project. Run `pip-audit -r requirements.txt` to check the pinned application dependencies against public vulnerability advisories.

Builds collect and fingerprint static assets, then run Gunicorn as a dedicated non-root account. The production web/worker containers use a read-only filesystem and temporary `/tmp`; web has a writable named `room_media` volume at `/app/media` for optional room photos (application UID/GID 1000). The [HTTPS deployment guide](docs/deployment.md) includes clean setup, restricted runtime database permissions, migrations, initial staff creation, TLS, verification, backups, and restore. For the selected `mbs.wdn.com.np` installation on Oracle Linux, follow the [private-network HTTP guide](docs/deployment-http.md). It uses port 80 and requires no certificate or private CA; browsers show **Not secure** because browser traffic is unencrypted.

The [verification report](docs/verification-report.md) records the production-branch test results, browser checks, deployment rehearsal, security fixes, and remaining deployment checks.

## Approval and booking lifecycle

Staff select **Requires approval** per room in **Staff desk → Rooms** or the room add/edit form; it defaults to checked. Employee submissions for checked rooms start **Pending** and hold the room/time, including the configured gap. Front Desk or Administrators open **Pending requests**, review details, and approve or reject. Rejection requires a reason visible to the requester. Employee submissions for unchecked rooms start **Approved** immediately and queue confirmation/check-in instructions. Capacity, availability and booking rules apply to both paths. Manual approval requires a verified staff session.

The wizard checks date/time/recurrence availability without creating a reservation and submits one server-validated request at the final step. A selected available card is not a hold; final saving rechecks room activity, capacity, schedule and conflicts.

Staff-created bookings are **Approved** immediately. A substantive employee edit follows the selected room's current policy: checked means **Pending**; unchecked means **Approved**. Staff edits retain Approved; a substantive staff edit to Pending can confirm it automatically only when the selected room is unchecked. An unchanged save preserves the existing state. Toggling a room does not rewrite saved bookings, so existing Pending requests remain Pending until review or a substantive eligible edit. Each recurring occurrence follows its room's policy and is reviewed separately when Pending. Owners and staff may cancel eligible bookings; cancelled and rejected records remain in history but release occupancy. Pending requests that have not been approved by the meeting start are cancelled automatically. Approval cannot revive rejected, cancelled, or expired records. Approved meetings proceed through **Checked in**, **Completed**, or **No show** after a missed check-in deadline.

## Operations and limits

`/livez/` checks the web process. `/healthz/` checks PostgreSQL and a worker heartbeat from the last two minutes, returning HTTP 503 when either is unavailable. The endpoints expose no credentials or configuration. Docker checks web, worker, proxy, and database. An unhealthy container needs operator attention; Docker restart policies restart exited processes, not merely unhealthy ones.

The worker reconciles approximately every 30 seconds and sends one message at a time with a ten-second SMTP timeout. A slow send can delay the next reconciliation by that timeout. Failed jobs and interrupted delivery leases recover after restart; messages whose reminders have become obsolete are labelled superseded rather than sent.

After SMTP is repaired, `python manage.py retry_failed_mail --all` requeues eligible failures that exhausted retries; `--id NUMBER` targets one. It supersedes obsolete booking messages and records the action in audit history.

This remains a single-server application. The owner has started company services on the selected HTTP installation. IT must verify employee-device DNS/routing, deployed-server relay authorization/mailbox receipt, representative usage, health monitoring and tested off-server backups. Certificate monitoring applies only if the alternative HTTPS profile is adopted. The agent's isolated test/rehearsal evidence does not replace company pilot acceptance.

Guides: [all documentation](docs/index.md), [features/use cases](docs/features-and-use-cases.md), [operations](docs/operations-runbook.md), [employees](docs/user-guide.md), [staff](docs/staff-guide.md), [troubleshooting](docs/troubleshooting.md), [architecture](docs/architecture.md), and [database design](docs/database-design.md).

SMTP/email credentials must be supplied by the system administrator during production deployment. No production email credentials are included in this repository.
