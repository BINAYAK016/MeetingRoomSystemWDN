# Troubleshooting and log reference

**Transgate Tech | Binayak Bhandari**

Production commands use **Oracle Linux**, `/opt/mbs/MeetingRoomSystemWDN`, branch `mbs-prod`, and **http://mbs.wdn.com.np** at **192.168.50.222**. Run Linux commands in that repository. Laptop commands use PowerShell and the local `compose.yaml`; they are identified separately. Use [operations](operations-runbook.md) for planned changes, backups and restoration, [HTTP deployment](deployment-http.md) for installation, and [staff instructions](staff-guide.md) for business actions.

## 1. First response

Collect the approximate time/timezone, page **path** such as `/staff/sign-in/`, action, visible message and support reference. Describe whether one person, everyone, one room or one action is affected. Never share an email sign-in/setup/check-in URL, password, code, cookie, `.env` or dump in a ticket. Check the booking's current status before assuming a failed email or stale screen means the booking failed.

Start with these read-only commands:

```bash
cd /opt/mbs/MeetingRoomSystemWDN
date -Is
git branch --show-current
git rev-parse --short HEAD
docker compose -f compose.prod.http.yaml ps -a
docker compose -f compose.prod.http.yaml logs --since 15m --tail=200 --timestamps web worker proxy db
curl --silent --show-error --max-time 15 --write-out '\nHTTP %{http_code}\n' http://mbs.wdn.com.np/livez/
curl --silent --show-error --max-time 15 --write-out '\nHTTP %{http_code}\n' http://mbs.wdn.com.np/healthz/
```

| Observation | Meaning | Next section |
| --- | --- | --- |
| Connection refused/timeout; no HTTP status | DNS, binding, routing, proxy or host | [Network](#4-network-dns-and-proxy) |
| `/livez/` is `ok`, `/healthz/` is 503 | Web responds; database or worker readiness failed | [Health](#3-health-and-worker-problems) |
| 403 session-check page | CSRF validation failed | [CSRF](#5-session-check-and-csrf-403) |
| 400/rejected hostname | Allowed-host/public-origin mismatch | [Configuration](#6-configuration-and-stale-containers) |
| 502/504 | Proxy could not complete upstream request | [Network](#4-network-dns-and-proxy) |
| Branded 500/503 | Application failure or unavailable database | [Application errors](#10-application-errors-and-static-assets) |
| Email missing after sign-in request | SMTP/relay/mailbox problem; generic success message alone proves no delivery | [Email](#7-email-sign-in-and-smtp) |
| Booking still pending | Review required when submitted, or saved Pending retained after policy changed | [Booking rules](#8-booking-availability-and-business-rules) |
| Release/reminder late | Check worker, deadline, booking state and outbox | [Health](#3-health-and-worker-problems), [email](#7-email-sign-in-and-smtp) |

A successful sign-in-page GET does not prove POST, SMTP, staff MFA or check-in works. Readiness does not prove inbox delivery.

## 2. Logs and support evidence

### Recent/live logs and incident windows

```bash
# Recent records with Docker timestamps.
docker compose -f compose.prod.http.yaml logs --since 30m --tail=300 --timestamps web worker proxy db

# Ctrl+C stops viewing; containers keep running.
docker compose -f compose.prod.http.yaml logs --follow --since 5m --tail=100 web worker proxy

# Replace these example UTC times with the actual incident window.
docker compose -f compose.prod.http.yaml logs --since '2026-10-07T10:15:00Z' --until '2026-10-07T10:25:00Z' --timestamps web proxy

# Bounded search for failure categories.
docker compose -f compose.prod.http.yaml logs --since 1h --no-color web worker proxy db | grep -E 'ERROR|WARNING|failed|unavailable|CSRF|TIMEOUT|status=5[0-9][0-9]|status=403'
```

Docker's [Compose logs reference](https://docs.docker.com/reference/cli/docker/compose/logs/) explains these options. `grep` exits 1 if no matches; that is not proof of health.

| Service | Logged information |
| --- | --- |
| `proxy` | Method, HTTP status, bytes, duration, upstream status, request ID. No URL/query, cookies or form body. Sensitive token routes omit access logging. |
| `web` | Gunicorn startup; safe HTTP failures, resolved view, exception class, optional SQLSTATE, sanitized source locations and request ID; CSRF/authentication categories. |
| `worker` | `released=N completed=N reminders=N sent=N`; notification ID/attempt/error class; cycle failure class. Quiet periods with no work are normal. |
| `db` | PostgreSQL startup/shutdown/recovery, authentication and database errors. Review operational details before sharing. |

Normal application logs intentionally omit raw exception messages, traceback locals and secret-bearing requests. They are not a full SMTP transcript or business audit. Use `/staff/audit/` for business actions. Proxy times include an offset; PostgreSQL/Gunicorn commonly log UTC; screens use Nepal time (UTC+05:45).

### Correlate a support reference

Use the displayed 32-character support reference from a 500/503 page, never the token from an email URL:

```bash
REQUEST_REF='REPLACE_WITH_32_CHARACTER_SUPPORT_REFERENCE'
docker compose -f compose.prod.http.yaml logs --since 1h --no-color web proxy | grep -F "$REQUEST_REF"
```

No result can mean a short time window, old recreated container or sensitive route with no proxy access record. `X-Request-ID` also carries the reference. Capture evidence **before** recreating containers, which removes their old locally accessible logs.

### Save a private incident log

```bash
umask 077
mkdir -p /root/mbs-support
chmod 700 /root/mbs-support
INCIDENT_FILE="/root/mbs-support/mbs-$(date -u +%Y%m%dT%H%M%SZ).log"
docker compose -f compose.prod.http.yaml logs --since 30m --tail=1000 --timestamps --no-color web worker proxy db > "$INCIDENT_FILE" 2>&1
chmod 600 "$INCIDENT_FILE"
printf 'Saved locally: %s\n' "$INCIDENT_FILE"
```

Review/redact before sharing. Never commit logs, dumps or `.env`. No external collector is included; IT chooses retention/rotation/monitoring. Compose logs only retrieves records retained by Docker's current logging driver.

## 3. Health and worker problems

| Check | Expected | Meaning |
| --- | --- | --- |
| `/livez/` | 200 text `ok` | Web can answer a simple request. |
| `/healthz/` | 200 JSON `status: ok`, `database: ok`, `worker: ok` | Database query works; worker reconciliation succeeded within 120 seconds. |
| `/healthz/`, database unavailable | 503, database `unavailable` | Database query failed. |
| `/healthz/`, worker unavailable | 503, database `ok`, worker `unavailable` | Heartbeat absent/stale. |
| `check_worker_health` | `ok`, exit 0 | Same heartbeat check via management command. |

503 may occur briefly during startup. `email: configured` means host/sender configured, not relay acceptance; readiness can be 200 with email unavailable.

```bash
docker compose -f compose.prod.http.yaml exec worker python manage.py check_worker_health
docker compose -f compose.prod.http.yaml logs --since 15m --tail=200 worker db
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.utils import timezone
from booking.models import WorkerHeartbeat
h = WorkerHeartbeat.objects.filter(pk=1).values('last_success_at', 'last_error_at').first()
print('now_utc=', timezone.now().isoformat())
print('heartbeat=', h)
PY
```

The loop attempts one due notification per iteration, normally about one second; reconciliation runs approximately every 30 seconds. SMTP has a ten-second timeout. Large queues do not all send in one reconciliation. Correct database/network/configuration failures before restarting. If the worker remains stuck after diagnosis:

```bash
# Recovery mutation: restart and resume queued work.
docker compose -f compose.prod.http.yaml restart worker
docker compose -f compose.prod.http.yaml logs --since 2m --tail=100 worker
docker compose -f compose.prod.http.yaml exec worker python manage.py check_worker_health
```

`run_booking_worker --once` is **not read-only**: it can cancel requests, release no-shows, complete meetings, create reminders and send email. Use `check_worker_health` for diagnosis. Avoid extra permanent interactive workers.

`restart: unless-stopped` acts when a process exits; it does not restart a container merely marked unhealthy. IT should alert on readiness, container state and heartbeat. Stale worker readiness can also prevent web/proxy startup readiness succeeding even when Gunicorn started.

## 4. Network, DNS and proxy

### Linux server checks

```bash
hostname -I
ip -brief address
getent ahostsv4 mbs.wdn.com.np
ss -ltnp '( sport = :80 )'
docker compose -f compose.prod.http.yaml port proxy 80
docker compose -f compose.prod.http.yaml logs --since 10m --tail=100 proxy web

# Bypass DNS, retaining the correct Host header.
curl --silent --show-error --max-time 15 --resolve mbs.wdn.com.np:80:192.168.50.222 --write-out '\nHTTP %{http_code}\n' http://mbs.wdn.com.np/livez/
```

Office IPv4 is `192.168.50.222`; `172.17.0.1` is Docker's bridge. If `--resolve` works while ordinary curl fails, inspect DNS. If both fail, inspect binding/proxy/routing. Raw-IP browser URLs can fail allowed-host validation and change cookies; keep the canonical hostname.

### Employee laptop checks (PowerShell)

```powershell
Resolve-DnsName mbs.wdn.com.np
Test-NetConnection mbs.wdn.com.np -Port 80
curl.exe --silent --show-error --max-time 15 --write-out '\nHTTP %{http_code}\n' http://mbs.wdn.com.np/livez/
```

If server-local tests work but laptops fail, IT checks routing/VPN/DNS/firewall. Inspect services without disabling them:

```bash
systemctl is-active docker firewalld
firewall-cmd --get-active-zones
firewall-cmd --list-all-zones
getenforce
ip route
docker network ls
```

Docker creates published-port filtering rules and integrates with firewalld. A host INPUT rule alone does not establish an office-only allowlist for forwarded Docker traffic. Verify access restrictions at the correct network/Docker forwarding layer; see [Docker packet filtering](https://docs.docker.com/engine/network/packet-filtering-firewalls/). Keep SELinux, firewalld and Docker filtering enabled.

| Symptom | Check/correction |
| --- | --- |
| `address already in use` | Identify port-80 owner with `ss`; review the intended conflicting service before changing it. |
| `cannot assign requested address` | Correct `HTTP_BIND_IP` to an actual office-interface address. |
| Subnet/allocation conflict | Check office routes/Docker networks; update subnet, dynamic range, proxy IP and trusted CIDR together; follow operations network-recreation instructions. |
| 502 after recreation | Check web health/logs/current image; current Nginx dynamically resolves `web:8000` through Docker DNS. |
| 504/slow requests | Check database/web logs and resource pressure, not just timeouts. |
| Browser changes to HTTPS | Check HTTPS-only browser settings or old HSTS from an HTTPS trial. The HTTP proxy sends no HSTS. |
| SELinux mount denial | Verify committed `:ro,Z`, file ownership, `ls -lZ deploy/*.sh deploy/*.template` and `ausearch -m AVC -ts recent` if installed. Correct the specific access/label. |
| Orphan `mail_init` warning | A local-profile service absent from production, not itself a failure. Verify service/project identity before targeted cleanup; preserve volumes. |

## 5. Session check and CSRF 403

**Let's start fresh** means the POST failed CSRF validation, not that the email/password was wrong. Session-backed CSRF protects login and every state-changing form.

1. Open a fresh form at `http://mbs.wdn.com.np/sign-in/` or `/staff/sign-in/`; submit in that same session and hostname.
2. Avoid stale tabs/back-button forms and hostname/IP/localhost switching; allow site cookies.
3. If fresh Chrome Incognito also fails, inspect the server/header rather than repeatedly clearing cookies.

```bash
# Filtered headers omit Set-Cookie.
curl --silent --show-error --dump-header - --output /dev/null http://mbs.wdn.com.np/sign-in/ | grep -Ei '^(HTTP/|Referrer-Policy:|X-Request-ID:|Location:)'
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.conf import settings
keys = ('PRODUCTION_ENABLED', 'HTTPS_ENABLED', 'PUBLIC_BASE_URL', 'ALLOWED_HOSTS',
        'SESSION_COOKIE_SECURE', 'SESSION_COOKIE_DOMAIN', 'CSRF_USE_SESSIONS',
        'CSRF_TRUSTED_ORIGINS', 'SECURE_REFERRER_POLICY')
print({k: getattr(settings, k, 'MISSING') for k in keys})
PY
docker compose -f compose.prod.http.yaml logs --since 5m --tail=100 web
```

Expected: production true, HTTPS false, public URL `http://mbs.wdn.com.np`, session secure false, session domain `None`, session CSRF true, trusted origins exactly that origin, referrer policy **same-origin**.

Earlier `no-referrer` made native browser POSTs send `Origin: null`; Django rejected them. The correction is in `392dfa5` and later versions. Verify the response header; pulling source alone does not update running Python code. See [verification report](verification-report.md) and [Fetch origin-header rules](https://fetch.spec.whatwg.org/#append-a-request-origin-header).

| Safe category | Likely reason | Action |
| --- | --- | --- |
| `missing_session` | Missing/expired CSRF session | Fresh form, cookie/hostname/environment check. |
| `missing_token` | Form token absent | Current form/templates/image. |
| `invalid_token` | Stale/mismatched token/session | Reload after sign-in/out or access/password change. |
| `origin_mismatch` | Wrong scheme/host/port or null Origin | Canonical URL, exact trusted origin, Host header, referrer policy. |
| `referer_rejected` | HTTPS referer validation failed | Alternative HTTPS profile: check origin/proxy scheme/context. |
| `other` | Other rejection | Correlate request ID and deployed version. |

Never disable middleware/tokens, enable DEBUG, trust arbitrary/null origins in production. The local opaque-origin accommodation is restricted to loopback development.

## 6. Configuration and stale containers

```bash
# Validate without printing expanded passwords.
docker compose -f compose.prod.http.yaml config --quiet

# Duplicate NAMES/counts only, never values.
awk -F= '/^[A-Za-z_][A-Za-z0-9_]*=/{count[$1]++} END {for (k in count) if (count[k]>1) print k, count[k]}' .env

# Explicitly nonsecret runtime settings only.
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.conf import settings
keys = ('DEBUG', 'PRODUCTION_ENABLED', 'HTTPS_ENABLED', 'PUBLIC_BASE_URL',
        'ALLOWED_HOSTS', 'EMPLOYEE_EMAIL_DOMAINS', 'MAIL_MODE', 'EMAIL_READY',
        'EMAIL_HOST', 'EMAIL_PORT', 'DEFAULT_FROM_EMAIL', 'EMAIL_USE_TLS',
        'EMAIL_USE_SSL', 'AUTH_TRUSTED_PROXY_CIDRS', 'TIME_ZONE')
print({k: getattr(settings, k, 'MISSING') for k in keys})
PY
```

Do not publish plain Compose `config`, full `docker inspect`, `printenv`, `.env` or Django database/authentication settings. Remove duplicate keys so each appears once. Environment names are `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, `SMTP_USE_TLS`, `SMTP_USE_SSL`, `DJANGO_FROM_EMAIL`; internal Django `EMAIL_*` settings are derived, not the environment contract.

Production profiles force production true, their own transport, and `wdn.com.np,transgate.com.np`. Editing `.env` alone cannot add a production employee domain. File-email mode, `/dev/mail/` and demo seeding are unavailable in both production profiles.

For a reviewed email/origin `.env` change only:

```bash
# Configuration mutation with brief service interruption.
docker compose -f compose.prod.http.yaml config --quiet
docker compose -f compose.prod.http.yaml up -d --no-deps --force-recreate --wait --wait-timeout 180 web worker proxy
```

`restart` retains the old environment. Python/templates/static changes need a build and recreation; use [controlled updates](operations-runbook.md). Documentation-only changes need no image rebuild. Existing-volume **Skipping initialization** is normal: changing bootstrap credentials in `.env` does not change stored PostgreSQL roles. Preserve working credentials/data and use deliberate rotation.

## 7. Email sign-in and SMTP

### Selected relay and connectivity

Previously accepted company settings:

```ini
DJANGO_EMAIL_BACKEND=smtp
DJANGO_FROM_EMAIL=mbs@wdn.com.np
SMTP_HOST=maildc01.wdn.com.np
SMTP_PORT=25
SMTP_USER=
SMTP_PASSWORD=
SMTP_USE_TLS=false
SMTP_USE_SSL=false
```

Acceptance from one source does not prove authorization of a new server IP or inbox arrival. IT must permit this sender/source. Credentials are used when relay policy requires them; adding a password cannot automatically fix sender rejection.

```bash
getent ahostsv4 maildc01.wdn.com.np
docker compose -f compose.prod.http.yaml logs --since 15m --tail=150 web worker

# Actual application network: DNS, connection and EHLO only; no AUTH/mail.
# For the selected plain-SMTP port-25 relay, not implicit SSL port 465.
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
import smtplib
import socket
from django.conf import settings
try:
    addresses = socket.getaddrinfo(settings.EMAIL_HOST, settings.EMAIL_PORT, type=socket.SOCK_STREAM)
    print('addresses=', sorted({a[4][0] for a in addresses}))
    with smtplib.SMTP(settings.EMAIL_HOST, settings.EMAIL_PORT, timeout=10) as smtp:
        code, _ = smtp.ehlo()
        print('ehlo_status=', code)
        print('capabilities=', sorted(smtp.esmtp_features))
except Exception as exc:
    print('smtp_error_class=', type(exc).__name__)
    print('smtp_status=', getattr(exc, 'smtp_code', None))
PY
```

EHLO success proves connectivity, not sender/recipient authorization. Use a matching connection type for an alternative IT-approved TLS relay.

### Send one deliberate test

This **sends real email**: enter an authorized recipient, run once, check Inbox/Junk. It never prints credentials. Backend acceptance does not prove inbox delivery.

```bash
docker compose -f compose.prod.http.yaml exec web python manage.py shell -c "from django.conf import settings; from django.core.mail import send_mail; recipient=input('Authorized test recipient: ').strip(); print('backend accepted count=', send_mail('MBS relay test', 'One test message from the company Meeting Booking System. Please confirm receipt.', settings.DEFAULT_FROM_EMAIL, [recipient], fail_silently=False))"
```

Exceptions from an interactive test may show sender/recipient and policy text; review before sharing. Never enable SMTP debuglevel, which can expose AUTH/message contents.

| Error | Likely cause | Next action |
| --- | --- | --- |
| `gaierror` | Relay DNS failure | Company DNS/VPN and container resolver. |
| `ConnectionRefusedError` | No listener/wrong port/active reject | Confirm endpoint/port. |
| `TimeoutError`, `SMTPServerDisconnected` | Routing/firewall/relay availability or protocol mismatch | Compare container EHLO and relay logs with IT. |
| `SMTPSenderRefused`, 554 policy rejection | Envelope sender/source policy denied | IT authorizes `mbs@wdn.com.np` from this server or supplies approved sender/relay; a password may not fix it. |
| `SMTPRecipientsRefused` | Recipient/domain/relay permission rejected | Exact mailbox and accepted destination domains. |
| `SMTPAuthenticationError` | Wrong credentials/AUTH policy | IT confirms account and permitted AUTH/encryption; password stays in private `.env`. |
| `SMTPNotSupportedError` | Requested STARTTLS/AUTH not advertised | Match settings to approved capabilities. |
| `SSLError` | TLS mode/certificate/trust mismatch | Correct endpoint/mode/company trust. |
| Disabled-backend warning | Disabled or missing host/sender | Configure/recreate services; queued jobs consume no retries while disabled. |
| Accepted but no Inbox message | Routing/quarantine/spam/mailbox after acceptance | Provide IT sender, recipient, test subject and timestamp for relay tracking. |

The selected relay uses both TLS/SSL false. Never enable both; that prevents startup. Mailbox domain need not equal the relay hostname, but organizer/staff identities need an allowed company domain.

### Authentication versus queued notifications

Employee links, staff codes and setup links send synchronously; failed delivery denies authentication. They are **not** recovered by `retry_failed_mail`. Repair SMTP and request a fresh link/code/setup. The employee check-email screen intentionally avoids account enumeration.

Booking events/reminders are worker-delivered outbox records. Inspect metadata without bodies/subjects/tokens/recipient lists:

```bash
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.db.models import Count
from booking.models import Notification
print('counts=', list(Notification.objects.values('status').annotate(total=Count('id')).order_by('status')))
rows = Notification.objects.filter(status__in=['pending', 'sending', 'failed']).order_by('next_attempt_at').values('id', 'reservation_id', 'reservation_revision', 'event_type', 'status', 'attempts', 'next_attempt_at', 'last_error')[:50]
print('queue_metadata=', list(rows))
PY
```

`pending` awaits delivery; `sending` holds a five-minute lease; `sent` means backend acceptance; `failed` retains error class; `skipped` displays **Superseded** for obsolete events. Failed attempts retry after approximately 2, 4, 8 and 16 minutes. The fifth failure is terminal until requeued. Its timestamp may be 32 minutes ahead, but there is no automatic sixth attempt. Interrupted leases recover after expiry; an interrupted final attempt becomes `WorkerInterrupted`. Ambiguous SMTP outcomes may cause duplicate delivery.

After SMTP repair, intentionally requeue eligible failures:

```bash
# Mutates outbox; the worker may send real emails.
docker compose -f compose.prod.http.yaml exec web python manage.py retry_failed_mail --id 123
# Alternatively all failed jobs:
docker compose -f compose.prod.http.yaml exec web python manage.py retry_failed_mail --all
```

Replace 123 with the diagnosed notification ID. Output is `requeued=N superseded=N`; eligible failures reset attempts and the action is audited. Obsolete revisions/events are skipped. This cannot recreate login tokens. Never update the outbox in SQL or resend obsolete check-in links.

## 8. Booking availability and business rules

| Symptom | Explanation/resolution |
| --- | --- |
| Unavailable after visible meeting end | Gap applies: default 10:00-11:00 occupies through 11:15. |
| Pending request blocks another person | Intended slot hold; staff approves/rejects. Expired requests cancel at start. |
| No approved meeting but room unavailable | Pending requests, closures, gap, holidays, activity or horizon. |
| Recurring series fails entirely | All occurrences save atomically; inspect every date/conflict. |
| Monthly recurrence gives one occurrence | Only dates within default 14-day horizon; later months booked manually. |
| Approved becomes pending after edit | Substantive employee edit in a room currently requiring approval; selected room's current setting applies. Staff edits of Approved retain approval. |
| Unchecked room still has Pending requests | A toggle never rewrites bookings. Existing Pending needs explicit staff review or a substantive valid edit in the unchecked room; an unchanged save preserves Pending. |
| Checkbox does not save | Staff password/code session required; with JavaScript it submits on change, otherwise use that row's Save button. Reload and check audit. A 403 requires CSRF investigation; do not disable CSRF. |
| Unchecked room booking confirmed but no email | Approved is a saved booking state, not proof of delivery. Inspect worker/outbox/relay as in section 7; the check-in deadline remains. |
| Old approval screen fails | Reload; changed/expired/cancelled/rejected request cannot be revived. |
| Date/time invalid | Future Nepal start, Mon-Fri hours, holidays, duration/increments/horizon; current policy may differ from defaults. |
| Staff override still conflicts | Never bypasses overlap, room/organizer activity or capacity. Move/cancel through UI or select another slot. |
| Senior-management third-floor priority | Front Desk decides/moves/cancels manually with reasons/notifications; no automatic preemption. |
| Deactivated room still has bookings | Deactivation prevents new reservations, not retroactive cancellation; staff reviews existing meetings. |
| New holiday/policy leaves meetings unchanged | No retroactive cancellation; staff reviews affected records. Current check-in deadline applies to existing approved meetings. |
| Other employee details denied | Ownership or verified staff required; expected privacy behavior. |
| Only one room listed | Staff must configure actual active rooms; production never seeds demo data. |
| Wizard shows unavailable for a free first date | All eligible recurring occurrences must be free, including gaps; inspect later dates in the preview/review. |
| Selected Available room fails final submission | Preview does not hold space; final save detects intervening conflicts, inactive rooms and capacity/policy changes. Retain entries and choose a valid alternative. |
| External or Internal + External rejected | Guest company is required for both; count email-listed people and additional no-email guests once each. |
| Wizard controls absent or room cards never update | Native form remains usable. Inspect browser console/Network for the static wizard asset and `/bookings/availability/` response; rebuild/recreate a stale image and load a fresh page. Share status/error text, not full request values. |
| Invalid form cannot be retried | Load current assets; client validation must not leave a prevented submission locked. Server errors retain data for correction. |

Read-only current policy/status totals:

```bash
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.db.models import Count
from booking.models import BookingPolicy, Reservation, Room, CompanyHoliday
fields = ('opens_at', 'closes_at', 'minimum_minutes', 'maximum_minutes', 'slot_minutes', 'gap_minutes', 'advance_days', 'check_in_minutes')
print('policy=', BookingPolicy.objects.filter(pk=1).values(*fields).first())
print('rooms=', list(Room.objects.values('is_active', 'requires_approval').annotate(total=Count('id')).order_by('is_active', 'requires_approval')))
print('reservations=', list(Reservation.objects.values('kind', 'status').annotate(total=Count('id')).order_by('kind', 'status')))
print('holiday_count=', CompanyHoliday.objects.count())
PY
```

Inspect individual bookings/audit in Staff desk. Direct SQL status/time edits bypass locking, notifications, revisions and audit.

### Room photo upload or display

| Symptom | Check |
| --- | --- |
| Upload rejected | Still JPEG/PNG/WebP only; at most 5 MiB and 12 million pixels. An extension alone does not prove readable image contents. |
| Form correction loses selected file | Browsers do not retain the file picker selection; select the upload again before resubmitting. |
| Replace/remove error | Choose a new upload or Remove current photo, not both. |
| Photo save reports storage problem | Check named `room_media` volume mounted at `/app/media`, directory ownership UID/GID 1000 and writable volume; application root remains read-only. |
| Photo request redirects to sign-in | Images require an authenticated session. Ordinary employee sessions cannot view inactive room photos. |
| Room has no photo | Optional and valid; staff can add one under Staff desk → Rooms → Edit. |
| Stored photo returns 404 after recovery | Database has only a filename; restore the matching photo archive, not only the dump. Missing files are not recreated from room records. |
| New schema field/endpoint fails after upgrade | Apply committed 0009/0010/0011 using the maintenance workflow, rerun `db_setup`, rebuild/recreate services; do not reseed rooms. |

Read-only storage diagnosis (no photo bytes or credentials printed):

```bash
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
import os
from pathlib import Path
from django.conf import settings
from booking.models import Room
root = Path(settings.MEDIA_ROOT)
photos = root / 'rooms' / 'photos'
print('process_uid_gid=', (os.getuid(), os.getgid()))
print('media_root=', str(root), 'photos_directory_exists=', photos.is_dir(), 'writable=', os.access(photos, os.W_OK))
if photos.exists():
    info = photos.stat()
    print('directory_uid_gid_mode=', (info.st_uid, info.st_gid, oct(info.st_mode & 0o777)))
references = list(Room.objects.exclude(photo='').values_list('photo', flat=True))
print('room_photo_references=', len(references))
print('missing_photo_files=', sum(not (root / name).is_file() for name in references))
PY
docker compose -f compose.prod.http.yaml logs --since 10m --tail 80 web
```

Expected application UID is 1000 and the photo directory is writable. Existing named volumes retain their own permissions; rebuilding the image cannot repair a separately misowned volume. Have IT inspect the selected project/volume and restore ownership through its reviewed maintenance process. Keep writers stopped during recovery; do not delete/reset the volume. See [photo backup and recovery](operations-runbook.md#room-photo-backup-and-recovery).

### Check-in/release

Check-in needs an approved meeting, at/after start and **before** the current deadline. Exactly start+15 minutes is too late under defaults. Opening a link displays confirmation; pressing the button changes status. The link proves organizer mailbox access and needs no earlier employee session. Expired/consumed/rescheduled/cancelled links fail.

Verified staff can check in through the booking page within the same window; they cannot late-check-in a no-show. If a new meeting is needed, create a new eligible booking. Release sets `no_show`, keeps history and releases occupancy; it does not delete. Stale workers can delay release while late check-in is already rejected. Booking writes reconcile overdue records; calendar GETs do not. Check heartbeat/logs and do not promise an exact release second.

## 9. Staff access and room editing

Admin is the custom **Staff desk**, not `/admin/`. Front Desk/Administrators have identical powers. Staff accounts using employee email login get only employee capabilities; staff actions need password plus code.

| Need/problem | Action |
| --- | --- |
| Room Edit | `/staff/rooms/` via Staff desk, **Edit** in row; `/rooms/` is employee directory. |
| Staff pages | `/staff/sign-in/`, password, eight-digit email code at `/staff/code/`. |
| New staff | Authorized operator bootstrap below; user sets their own password from setup email. |
| Invalid/expired code | 10-minute code, five guesses; request fresh code. Password/access changes invalidate challenges. |
| Expired setup | One-hour link; another staff sends fresh setup via People, or operator reruns bootstrap. |
| Access update invalidates session | Sign in again with current role. |
| Inactive account | Authentication denied; staff reviews/reactivates only when authorized. |
| Self-revoke refused | People prevents you from removing your own staff/activity. There is no separate last-staff concurrency guarantee; retain authorized operator recovery access. |
| Forgotten password | Another staff sends setup email or authorized operator bootstrap; SMTP must work. |

```bash
# Privileged mutation: grants/reenables staff and sends setup email.
# Replace with the approved person's allowed company address.
docker compose -f compose.prod.http.yaml exec web python manage.py create_staff_account person@wdn.com.np
```

Email case is normalized; rerunning does not duplicate users. The role may be enabled before delivery failure; repair SMTP and rerun the same address. Avoid shared passwords or technical superusers as business onboarding. See [staff guide](staff-guide.md).

## 10. Application errors and static assets

Record time/path/support reference. A refresh succeeding does not identify the earlier cause. An old screenshot without matching failure context cannot establish a specific server defect.

```bash
docker compose -f compose.prod.http.yaml logs --since 20m --tail=300 web worker db proxy
docker compose -f compose.prod.http.yaml exec web python manage.py check
docker compose -f compose.prod.http.yaml exec web python manage.py showmigrations booking
docker compose -f compose.prod.http.yaml exec web python manage.py migrate --check
docker compose -f compose.prod.http.yaml images
```

`showmigrations` and `migrate --check` do not apply migrations. Schema changes require backup, stopped writers, committed migrations and `db_setup` via operations. Never generate migrations on the server or run web/worker permanently as database administrator.

Older sync Gunicorn could time out on idle browser connections. Current image uses two threaded workers/four threads each and no unused control socket, supporting the read-only filesystem. If logs show `WORKER TIMEOUT`/socket startup errors, verify current image/build; resource pressure/database slowness need separate diagnosis.

CSS/logo/static manifest errors may indicate stale/mismatched builds or asset paths. Assets collect/fingerprint during image build. Rebuild/recreate through controlled updates and hard-refresh; do not write files into a read-only production container. Branding/fonts are local/system assets; no CDN font dependency is required.

Alternative HTTPS deployment uses its own Compose/certificate guide. Selected HTTP intentionally has no certificate, redirect, HSTS or secure-cookie transport flag. `check --deploy` may report these transport warnings; maintain the chosen profile consistently while troubleshooting. [Django deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/).

## 11. Database, disk and Docker

```bash
systemctl status docker --no-pager
journalctl -u docker --since '30 minutes ago' --no-pager
df -h / /opt /var/lib/docker
df -i / /opt /var/lib/docker
docker system df
docker stats --no-stream
docker compose -f compose.prod.http.yaml logs --since 15m --tail=200 db
docker compose -f compose.prod.http.yaml exec db sh -c 'pg_isready -U "$POSTGRES_USER" -d "$POSTGRES_DB"'
```

Inspect disk/inodes/database before repeated restart. Never erase volumes/database files, globally prune Docker or delete business/audit history to free space. Review image/log/backup retention deliberately with protected off-server copies.

Safe runtime identity/privileges:

```bash
docker compose -f compose.prod.http.yaml exec -T web python manage.py shell <<'PY'
from django.db import connection
with connection.cursor() as c:
    c.execute('SELECT current_database(), current_user')
    print('identity=', c.fetchone())
    c.execute('SELECT rolsuper, rolcreatedb, rolcreaterole FROM pg_roles WHERE rolname=current_user')
    print('superuser_createdb_createrole=', c.fetchone())
    c.execute("SELECT has_table_privilege(current_user, 'audit_events', 'SELECT'), has_table_privilege(current_user, 'audit_events', 'INSERT'), has_table_privilege(current_user, 'audit_events', 'UPDATE'), has_table_privilege(current_user, 'audit_events', 'DELETE')")
    print('audit_select_insert_update_delete=', c.fetchone())
PY
```

Expect application role, role flags all false and audit privileges `(True, True, False, False)`. Administrators retain controlled recovery powers; do not replace the restricted runtime role.

| Error | Investigation |
| --- | --- |
| Password authentication | Existing-volume role password vs `.env`; preserve working credentials, use controlled recovery/rotation. |
| `db` unreachable | DB container/project/internal network; no need to publish PostgreSQL. |
| Missing relation | Image/schema/migration state; maintenance migration. |
| Table/sequence permission | `db_setup` after migration, distinct admin/runtime roles. |
| Exclusion conflict | Expected overlap guard; choose another slot, keep constraint. |
| No space | Filesystem/inodes; protect data before targeted cleanup. |
| Recovery/not ready | PostgreSQL/storage logs; allow normal recovery, investigate repeat failures. |
| Daemon unavailable | Start/check Docker; laptop Linux engine below. |

Failed migrations/lost databases need a tested backup and controlled restore in [operations](operations-runbook.md). Archive listing alone is not restoration proof.

## 12. Laptop problems (PowerShell)

Run local commands in the local repository, without production `-f`:

```powershell
Set-Location 'C:\Users\Dell\Documents\Codex\2026-09-28\files-mentioned-by-the-user-meeting\outputs\meeting-room-booking'
docker version
docker compose version
docker info --format '{{.ServerVersion}}'
docker compose ps -a
docker compose logs --since 15m --tail=150 web worker db
Invoke-WebRequest http://127.0.0.1:8000/healthz/
```

Missing `dockerDesktopLinuxEngine` pipe means Docker Desktop's Linux daemon is not ready. Start Desktop, wait for running state, ensure Linux containers, rerun `docker info` before Compose. Check `wsl --status`/`wsl --list --verbose` if needed; do not reset/uninstall and discard data as the first fix.

```powershell
# Normal restart after initial setup.
docker compose up -d db
docker compose up -d web worker
```

Use `127.0.0.1` consistently. Local file-mail links/codes appear at `/dev/mail/`; production has no such inbox. Seed demo rooms only into an empty local directory or add through staff UI; README has initial setup. Linux `<<'PY'` snippets belong on Linux; operations shows PowerShell here-string alternatives. Replace local log `grep` with `Select-String`.

## 13. Reports, audit and verification

Utilization counts scheduled meeting minutes for checked-in/completed bookings, against the **current** Mon-Fri policy/holiday calendar minus active closures. Reports include currently inactive rooms. Gaps, unchecked approved/pending, no-shows and cancellations are not used minutes. Historical rule changes can alter results; this is an operational estimate, not immutable past-policy reconstruction.

Excel requires staff access: use the report page link to `/staff/reports.xlsx`, review date order/range and safe logs. Formula-looking user text is literal in export. Compare [feature definitions](features-and-use-cases.md) before comparing personal spreadsheet totals. Audit is append-only for runtime, with no UI delete/edit or automatic purge. GET page views are not a complete access audit.

### Local automated checks

```powershell
docker compose build
docker compose run --rm test
docker compose run --rm web python manage.py check
docker compose run --rm web python manage.py makemigrations --check --dry-run
```

Tests create/destroy a separate test database and need local administrator configuration. Never run with production credentials. [Verification report](verification-report.md) records the earlier 210-test PostgreSQL pass and browser/restore rehearsals; these do not replace an office pilot.

### Close an incident

Verify the original action on an affected device, readiness/heartbeat, current booking status and required email receipt. Record cause, remedy, commit/configuration version, time and remaining limitations. Review failed outbox before retrying; confirm backup/monitoring after recovery. A refresh or running container alone is not sufficient evidence.
