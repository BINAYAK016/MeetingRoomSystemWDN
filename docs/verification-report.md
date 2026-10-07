# Production verification — 7 October 2026

**Transgate Tech | Binayak Bhandari**

## Delivery and scope

Production work is on `mbs-prod`, created from clean `main` at `22caa31`. The existing demo branch, running demo containers, database, SMTP settings, and company accounts were preserved. The final commit IDs and remote push result are reported in the handover message. This report covers locally verified code and an isolated production deployment rehearsal; company-server deployment has not occurred.

Inspection covered every URL pattern, templates/static assets, forms, identity and staff permissions, model relations/constraints/indexes, migrations, booking services, recurring occurrences, calendar, worker/outbox, reports/Excel, audit history, configuration, Docker/TLS/runtime database permissions, seed/bootstrap and backup tools. This application serves HTML forms plus readiness/liveness JSON; it has no public REST API.

## Approval workflow

- Employee creation produces **Pending**. Pending requests hold the complete occupied interval and gap through the PostgreSQL exclusion constraint.
- Verified staff review a dedicated queue and approve a future request or reject it with a required reason visible to its requester. Approval/rejection actors and timestamps are stored and audited.
- Staff creation is approved. Employee substantive edits to approved meetings return them to pending and invalidate previous links/notifications. Unchanged edits preserve approval; staff edits retain the current pending/approved state.
- Rejected/cancelled records release their slot and remain in history. Invalid transitions cannot revive them. Unapproved requests expire as cancelled at the meeting start; approved meetings use the existing check-in/completed/no-show lifecycle.
- Recurrence remains atomic and finite inside the two-week horizon; each occurrence is reviewed separately. Front Desk handles room priority manually.

## Reproduced failures and fixes

| Defect | Evidence and fix |
| --- | --- |
| Idle TCP connections causing HTTP 500 before Django | Two sync Gunicorn workers with timeout 3 seconds and two idle sockets returned two HTTP 500s, with `WORKER TIMEOUT` and `no URI read`. The same five-second probe with four threads per worker returned no 500/timeouts; subsequent requests returned 200. Deployment now uses gthread and disables the unused control socket for read-only startup. A regression exercises the actual Docker CMD against an isolated WSGI fixture. |
| Database session load/save failure | Injected failures during staff sign-in reproduced the recovery path. Outer safety middleware and database-free error rendering now return safe 503, preserve the session cookie, and recover to rooms 200 after the dependency recovers. Unexpected exceptions still return 500 and retain safe diagnostics. |
| Malformed URL input | Unicode numeric filters previously reached `int()` and raised ValueError; invalid UTF-8 password UID raised UnicodeDecodeError. Bounded ASCII checks and decoding guards now return safe pages/errors. |
| Calendar room activation race | A room activated between the room and reservation queries could cause a KeyError. Reservations now use the same room-ID snapshot; a regression reproduces activation between the queries and verifies load and refresh. |
| HTTPS public-port CSRF failure | Actual HTTPS POSTs on port 9444 failed because proxy Host omitted the public port. Django now trusts exactly the validated HTTPS public origin. Valid origin/referer/token POSTs pass; wrong/null origins and missing tokens remain rejected. Final real HTTPS approval/rejection passed. |
| Native browser form CSRF failure | Company GET returned `Referrer-Policy: no-referrer`; Chrome native employee submission reproduced 403 while a scripted request with explicit correct Origin passed 200. `no-referrer` causes native form POSTs to serialize Origin as null. The application now uses `same-origin`; native Chrome employee and staff submissions passed against an isolated production HTTP instance. Null/wrong origins and missing/invalid tokens remain denied. |
| Approval/access and stale mail races | Sorted user locks precede room/reservation locks and revalidate current role/activity. Concurrent decisions commit one outcome; organizer deactivation prevents waiting approval. Reservation revisions supersede stale mail, and same-time reapproval can queue a fresh reminder. |

The user reported intermittent staff sign-in/rooms errors that cleared after refresh, without a timestamp or screenshot. Available demo logs contained startup lines only. The defects above were reproduced and fixed; **the exact cause of those earlier individual incidents remains unconfirmed**. Future 500/503 responses display a support reference matching safe server logs and the X-Request-ID header.

## Security and database

Backend tests cover employee IDOR, foreign edit/cancel attempts, forged approval/staff flags, MFA bypass, stale/deactivated sessions, single-use token/code expiry and guesses, password setup, CSRF, escaped XSS content, literal Excel values, invalid form fields and malicious-looking filters. ORM parameterization is retained; no raw user-built SQL or permissive CORS is added.

Both production profiles retain HttpOnly/SameSite cookies, CSRF checks, CSP/frame denial, no-store private/error responses, bounded requests/timeouts, exact email domains, trusted proxy IP, disabled debug/development inbox, nonroot/read-only containers and an internal database network. The HTTPS profile additionally enables HTTPS redirects, secure cookies and HSTS. The selected HTTP profile explicitly omits those transport settings. Error logs retain view, exception class, safe source locations/SQLSTATE and request reference without exception values, tokens, credentials or request URLs. Proxy access logs retain status/timing/reference without query values or personal headers.

Migration `0008_booking_approval` atomically maps existing confirmed records to approved, adds review metadata/revision fields, a pending index, rejection validation and an exclusion constraint including pending. No reviewer is invented for legacy meetings. Fresh migrations and 0007→0008 data preservation passed. Round-trip rollback tests passed: approved→confirmed, pending/rejected→cancelled, unsent request/rejection mail superseded, sent history retained. Stop writers, back up, and reapply runtime grants during updates. Runtime cannot create schemas or modify/delete/truncate audit history.

## Automated gates

| Gate | Final result |
| --- | --- |
| Full PostgreSQL suite | **210 passed**, 31.580 seconds on the final browser-CSRF fix image; separate test DB created and removed. Earlier HTTPS/HTTP support suites passed 186/202 tests. |
| Fresh migration chain | All Django migrations and booking 0001–0008 passed |
| Forward/reverse migration tests | Legacy data, new guards, rollback mail and re-upgrade passed |
| Concurrency/transactions | Conflicting pending creates/edits, buffer/closure conflicts, atomic recurrence, competing decisions, access changes, login/code and check-in races passed |
| Email | Disabled/configured backend, failures/zero delivery, retry/lease, request/rejection/approval/cancellation, revision/reminder checks and local fake SMTP relay passed; no company mail sent |
| Ruff lint/format | Passed; 65 Python files formatted |
| Syntax/system checks | Python compilation, JavaScript syntax, Django system checks passed |
| Migration drift | No changes detected |
| Docker build | Passed; 130 static files copied, 388 post-processing outputs |
| Dependency audit | pip-audit 2.10.1: no known vulnerabilities in pinned application requirements at audit time |
| Earlier HTTPS production Django check | Exit 0; unsilenced W005/W021 for HSTS subdomains/preload, pending IT domain-wide policy |
| Static type checker | Not configured; no formal type-check success is claimed |
| GitHub Actions | CI workflow covers lint, migrations, tests, audit and build; hosted runner result is separate from this local report |

Negative tests intentionally log denied access, injected errors and mail failures. These are assertions, not production errors suppressed to pass a gate.

## Actual browser checks

Manual browser work used a separate database and local file email at port 8020. Employee email-link login, staff password/email-code login, logout/relogin and persistence passed. Verified combined room search/capacity/location/facility filtering, details, overlap rejection against pending occupancy, employee pending creation, My bookings/history, profile save, staff authorization redirect, approval and required rejection reason, owner rejection feedback, employee edit requiring reapproval, owner cancellation, staff cancellation, room add/edit/deactivation and inactive-room exclusion. Confirm dialogs support Go back, keyboard focus and Escape; confirmed approve/reject/cancel actions were exercised. A real Excel file downloaded; the final browser console had no warning/error entries.

Direct URL plus refresh checks covered:

| Employee/common | Staff |
| --- | --- |
| Overview; rooms; room details; calendar day/week; new request; My bookings/history; request detail/edit; profile; sign-in/confirmation/logout | Staff sign-in/code; dashboard; pending/all bookings; room list/add/edit; closure list/new; rules; holidays; people; reports; audit; calendar month |

Back/forward navigation passed. Desktop 1280, mobile 390 and tablet 768 viewports were inspected; tested page widths stayed within the viewport and table/navigation overflow remained inside scrollable containers. Viewport overrides were reset. Native JavaScript confirmation initially stalled the browser test tool; the interface now uses an accessible in-page dialog, and its actions were retested successfully. Password setup, access grants/revocations, closure/holiday/rule mutations, check-in/deadline jobs and pagination are covered by integration tests; they are not all claimed as manual browser mutations.

## Earlier isolated HTTPS production deployment rehearsal

Actual production Compose ran with synthetic secrets, disabled SMTP, isolated DB/network/volume, a trusted test certificate and loopback HTTPS 9444. Verified:

1. Fresh migrations, runtime role setup, healthy proxy/web/worker/database, UID 1000 and read-only application filesystem with writable /tmp.
2. Runtime ordinary DML and audit insert allowed; schema creation/audit UPDATE/DELETE/TRUNCATE denied (SQLSTATE 42501).
3. HTTPS/TLS, HSTS, CSP, no-store/nosniff and secure cookies; 19 authenticated routes each direct/repeated GET 200.
4. Valid-CSRF employee approval denied without changing pending state; real HTTPS employee create→staff approve→owner Approved and create→staff reject→owner Rejected/reason passed on the final image.
5. Actual backup.sh produced a validated 88,530-byte custom dump. pg_restore into a separate database succeeded; room/user/reservation/audit/notification counts matched 1/2/1/1/2 at the backup point.
6. DB outage readiness 503/liveness 200 and DB recovery without app restart; naturally stale worker after 127 seconds readiness 503 and recovery after restart.
7. Recreated web changed frontend IP while nginx continued running; Docker DNS re-resolution restored all probes. Hashed CSS/JS returned 200 with immutable cache headers.

Rehearsal containers/networks were stopped and removed without deleting volumes. Synthetic evidence/backups stayed outside Git. The existing demo was not modified.

## Selected HTTP production deployment rehearsal

After the user selected HTTP for the office network, a separate final-image rehearsal ran at `http://127.0.0.1:9120`, with a fresh isolated database/network, synthetic secrets and a local SMTP capture service. No company relay was contacted. The existing demo remained untouched.

Verified on the final HTTP-support image:

1. Full PostgreSQL suite: **202 tests passed** in 33.125 seconds, including 16 new HTTP-production settings/authentication tests. Django system checks, migration drift, Ruff lint/format, Docker build, and both Compose profiles' quiet configuration checks passed.
2. Fresh migrations through `0008`, restricted runtime role setup, and healthy database/web/worker/proxy startup. Runtime role superuser/database-creation/role-creation flags were all false.
3. Actual HTTP employee email-link confirmation and staff password plus emailed-code POSTs succeeded using captured synthetic SMTP messages. Employee approval was denied; staff approval and rejection persisted with the organizer-visible rejection reason.
4. Session cookies remained HttpOnly/SameSite Lax without Secure. HTTP produced no HTTPS redirect or HSTS, and the proxy mounted no certificate. Development inbox access returned 404 even on loopback in production mode.
5. Wrong, null and different-port origins, and missing CSRF tokens, returned 403. Valid origin and session-token POSTs passed. Both production profiles reject file-email mode; local development retains its separate email inbox.
6. The HTTP profile requires an explicit bind IP; blank `HTTP_BIND_IP` failed configuration validation. The environment generator selected the HTTP template, generated independent secrets, rejected `--http` without `--production`, and refused to replace an existing `.env`.
7. Actual `deploy/backup.sh`, selected with `COMPOSE_FILE=compose.prod.http.yaml`, produced a verified **89,358-byte** custom-format dump. Restore into a separate database succeeded and matched room/user/reservation/audit counts of **1/2/2/6**.

All rehearsal containers/networks were stopped and removed without deleting volumes. Synthetic SMTP evidence, secrets and backups stayed outside Git. This verifies the local HTTP profile; company-server DNS, network access, SMTP authorization and mailbox delivery still require the operator checks in [the HTTP deployment guide](deployment-http.md).

## Native-browser CSRF correction

The new company-server screenshot was reproduced in a separate Chrome tab. Effective running HTTP settings were correct, and a fresh scripted session with an explicit correct Origin passed. The real response still used `Referrer-Policy: no-referrer`. Per the [Fetch standard's Origin-header algorithm](https://fetch.spec.whatwg.org/#append-a-request-origin-header), this policy makes native form submissions send `Origin: null`, which Django rejects. Earlier scripted production rehearsals explicitly supplied Origin and did not exercise this browser-generated header.

The setting is now `SECURE_REFERRER_POLICY="same-origin"`, retaining same-origin referrers while withholding them from other sites. Actual native Chrome employee submission reached the normal request-received page, and staff submission reached normal credential validation, on a separate production-mode HTTP instance at `mbs-csrf.localhost:9120`. Both used dummy invalid credentials; no company email or successful sign-in is claimed for these probes. The company server still requires pulling and rebuilding the update.

The final image passed **210 PostgreSQL tests** in **31.580 seconds**, Django check, migration drift, Ruff lint/format and the Docker build. New regression coverage checks employee/staff response policy plus safe CSRF rejection diagnostics. Failures log only fixed categories and a validated request reference, never raw reasons, Origin/Referer values, cookies, credentials or tokens. The error page now gives site-neutral guidance and returns staff forms to staff sign-in. CSRF enforcement is unchanged.

Browser screenshot evidence is retained outside Git as `outputs/mbs-csrf-fixed.jpg`. Isolated review containers/networks were removed without deleting volumes; the existing demo was preserved. Company booking/staff records were not changed; company probes used only anonymous form sessions.

## Deployment handover

The selected company installation is **http://mbs.wdn.com.np**, bound to **192.168.50.222:80**, using `compose.prod.http.yaml`. Follow [the HTTP deployment guide](deployment-http.md); no certificate or private CA is required. The following commands describe the retained HTTPS profile.

Required: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and matching HTTPS `DJANGO_PUBLIC_BASE_URL`. Review proxy subnet/trusted IP settings if the defaults conflict. The HTTPS profile forces HTTPS; the HTTP profile forces HTTP. Both force production mode and allow `wdn.com.np,transgate.com.np`.

IT supplies SMTP separately: `DJANGO_EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `DJANGO_FROM_EMAIL`, `SMTP_USER`/`SMTP_PASSWORD` when required, and mutually exclusive `SMTP_USE_TLS`/`SMTP_USE_SSL`. Keep mail disabled while unconfigured; startup/bookings remain usable and jobs are not falsely marked delivered. Mailbox sign-in requires working delivery. No production credentials are committed.

On the company Linux server, after internal DNS/firewall/TLS and .env are prepared:

```sh
git clone --branch mbs-prod https://github.com/BINAYAK016/MeetingRoomSystemWDN.git
cd MeetingRoomSystemWDN
docker run --rm -v "$PWD:/workspace" -w /workspace python:3.12-slim python deploy/create-env.py --production
# Edit .env; install approved fullchain.pem and privkey.pem under deploy/certs.
chmod 600 .env deploy/certs/privkey.pem
docker compose -f compose.prod.yaml config --quiet
docker compose -f compose.prod.yaml build --pull
docker compose -f compose.prod.yaml up -d db
docker compose -f compose.prod.yaml run --rm migrate
docker compose -f compose.prod.yaml run --rm db_setup
docker compose -f compose.prod.yaml up -d web worker proxy
curl --fail https://YOUR-INTERNAL-HOST/healthz/
# Once approved SMTP is configured:
docker compose -f compose.prod.yaml exec web python manage.py create_staff_account APPROVED-PERSON@wdn.com.np
sh deploy/backup.sh
```

See [deployment](deployment.md) for exact updates, mail enablement, setup, monitoring, backup scheduling and restore commands; [README](../README.md) for laptop setup; [employee](user-guide.md) and [staff](staff-guide.md) for operation.

## Remaining verification

Company-server DNS, firewall/VPN, actual SMTP authorization and both domains' mailbox delivery, backup storage/retention, an on-server restore drill and representative office load await operator verification. The server OS, internal domain and office-interface IP have been supplied; the isolated local rehearsal does not prove those company-server checks. The specific earlier intermittent incident remains unattributed. No company deployment or sustained capacity benchmark is claimed. Direct HCL/Outlook integration remains deferred by agreement. Single-server failure, periodic worker release and possible duplicate SMTP delivery after an ambiguous response remain documented operating limits. For the optional HTTPS profile, HSTS domain-wide flags require IT approval.
