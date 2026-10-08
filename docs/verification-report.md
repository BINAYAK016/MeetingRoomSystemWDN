# Production verification — updated 8 October 2026

**Transgate Tech | Binayak Bhandari**

## Delivery and scope

Production work is on `mbs-prod`, created from clean `main` at `22caa31`. Earlier production review preserved the existing demo branch, running containers, database, SMTP settings and company accounts. The 8 October local upgrade is recorded separately below. The final commit IDs and remote push result are reported in the handover message. This report covers locally verified code and isolated deployment rehearsals. The owner has separately installed the company HTTP services; these local checks do not establish company-server acceptance.

Inspection covered every URL pattern, templates/static assets, forms, identity and staff permissions, model relations/constraints/indexes, migrations, booking services, recurring occurrences, calendar, worker/outbox, reports/Excel, audit history, configuration, Docker/TLS/runtime database permissions, seed/bootstrap and backup tools. This application serves HTML forms, authenticated read-only availability/employee-suggestion JSON and readiness/liveness JSON; it has no public REST API.

## Approval workflow

- Employee creation in a room with **Requires approval** checked produces **Pending**; an unchecked room produces **Approved** automatically. Pending requests hold the complete occupied interval and gap through the PostgreSQL exclusion constraint. New/previously configured rooms default to checked in migration 0011.
- Verified staff review a dedicated queue and approve a future request or reject it with a required reason visible to its requester. Approval/rejection actors and timestamps are stored and audited.
- Staff creation is Approved. Employee substantive edits follow the selected room's current setting: checked → Pending; unchecked → Approved automatically. Staff edits retain Approved; substantive edits to Pending in unchecked rooms can confirm automatically. Previous links/notifications are invalidated after substantive changes. Unchanged edits and room toggles preserve saved statuses.
- Rejected/cancelled records release their slot and remain in history. Invalid transitions cannot revive them. Unapproved requests expire as cancelled at the meeting start; approved meetings use the existing check-in/completed/no-show lifecycle.
- Recurrence remains atomic and finite inside the two-week horizon; each occurrence follows its room policy and is reviewed separately when Pending. Front Desk handles room priority manually.

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

| Gate | Latest result / earlier evidence |
| --- | --- |
| Full PostgreSQL suite | **323 passed in 39.242 seconds on 8 October 2026**; separate test DB created and removed. Prior room-policy baseline: 281 passed in 43.153 seconds; prior wizard/photo baseline: 244 passed in 40.439 seconds; earlier browser-CSRF baseline: 210 passed in 31.580 seconds; earlier HTTPS/HTTP support: 186/202 passed. |
| Fresh migration chain | All Django migrations and booking **0001–0011** passed; the existing local installation upgraded through 0011 without resetting records or booking statuses. |
| Forward/reverse migration tests | Legacy data, new guards, rollback mail and re-upgrade passed |
| Concurrency/transactions | Conflicting pending creates/edits, buffer/closure conflicts, atomic recurrence, competing decisions, access changes, login/code and check-in races passed |
| Email | Multipart text/HTML, inline CID wordmark, escaped user content, authentication/event messages, organizer-only check-in, recipient actions and revision/state checks passed. Existing disabled/configured backend, retry/lease and local fake-relay coverage also passed; no company mail sent |
| Ruff lint/format | Full repository `ruff check .` passed; `ruff format --check .` passed for **81 Python files** on 8 October 2026. |
| Syntax/system checks | Current JavaScript syntax and Django system checks passed. Python compilation passed in the earlier recorded baseline. |
| Migration drift | Current `makemigrations --check --dry-run` reported no changes. |
| Docker build | Current invited-meeting/professional-email build and collectstatic passed. Prior wizard/photo build: **135 static files copied, 401 post-processing outputs**. |
| Dependency audit | **Earlier 8 October 2026 wizard/photo release:** pip-audit 2.10.1 completed full application-requirement resolution, including Pillow 12.3.0, with exit 0 and no known vulnerabilities found at audit time. |
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

## Documentation-only release verification - 7 October 2026

This release changes documentation and adds an optional ReportLab handbook builder, with no application behavior or database migration changes. Existing application test evidence above remains the baseline; the full application suite was not rerun for prose changes.

- Reviewed feature/employee/staff documentation against models, forms, views, services, templates and worker: permission/state/notification matrices, complete URL catalogue and 28 use cases.
- Validated all 13 Markdown documents: 106 local links/anchors, balanced fences, 90 Bash/sh code blocks, nine embedded Python snippets and 12 PowerShell blocks. Syntax-only checks did not execute operational examples.
- The feature catalogue covers all 43 configured URL patterns, including protected actions and generated private-link routes.
- Ruff lint and formatting pass across all 70 Python source files, including the optional builder; Git whitespace checks pass.
- Ran the six read-only troubleshooting Django diagnostics against a separate PostgreSQL 17 project with SMTP disabled. Confirmed configured policy, queue metadata, restricted runtime identity and audit SELECT/INSERT-only permissions.
- Exercised the documented separate-database restore pattern on that isolated project: a trusted 87,294-byte custom-format dump restored one user, room, reservation, notification and audit event each; all five counts matched. Verified restored runtime audit INSERT/UPDATE/DELETE privileges `(True, False, False)` and the validated overlap constraint. The live-target name guard rejected creation against the selected source database.
- No worker was started for the restore drill and no external email, company account or company server mutation was performed. Isolated containers/networks were removed with the QA volume retained; the existing local demo was left healthy.
- Generated the complete handbook from 11 maintained guides, rendered its pages and checked contents/bookmarks, tables, diagrams, command displays, margins and glyphs. Long command displays wrap for print; Markdown remains the copyable source.

The optional documentation dependency is separate from application requirements. Rebuild the handbook after source-guide changes and review the latest rendered pages before committing it. Company-side acceptance, monitoring and recovery arrangements remain the operator's responsibility.

## Booking wizard and room photos - 8 October 2026

The following records the prior wizard/photo baseline, before the subsequent per-room approval release.

This release changes application behavior as well as documentation: Schedule & details → Attendees → Review & confirm, real whole-series room availability, Internal + External meetings, and optional staff-managed room photos. Committed migrations `0009_mixed_meeting_type` and `0010_room_photo` preserve existing records. No room reseeding is part of the upgrade. A local database backup was taken before upgrading the existing laptop installation.

### Automated verification

- Final clean PostgreSQL run: **244 tests passed in 40.439 seconds**; Django system check reported no issues. Early runs exposed historical migration-test cleanup that restored only schema 0008, leaving later photo-model tests on an incomplete schema; cleanup now restores the current migration graph leaf. The final result is the clean rerun, not those earlier failed attempts.
- Availability coverage checks authenticated GET-only access, active room metadata, generic occupied ranges without private meeting content, all occupying/released statuses, both meeting buffers, every recurrence occurrence, working-day skips, edit ownership/state and single-occurrence exclusion, staff verification/overrides, read-only behavior, page configuration/prefills, short-office-hour defaults and final-save revalidation after preview.
- Mixed meeting coverage requires guest company in form, service and database. Switching recurrence back to One meeting ignores a stale until date instead of rejecting an otherwise valid single meeting.
- Photo coverage checks optional upload, authenticated viewing, staff second factor, inactive-room privacy, supported/corrupt/animated/oversized images, metadata removal and image resizing, replace/remove commit cleanup, new-file cleanup on database failure, preservation on storage failure, conflicting remove/upload, and arbitrary-path/symlink escape rejection.
- Full repository `ruff check .` passed and `ruff format --check .` passed for 75 Python files. `node --check` passed for wizard and shared application JavaScript. The current pip-audit 2.10.1 run resolved the full application requirements, including Pillow 12.3.0, and reported no known vulnerabilities with exit 0.

### Actual browser and persistence checks

A separate local QA instance used file-email login; no company SMTP relay or production account was used. Browser actions verified:

1. Schedule initialization and required-title/guest-company validation; selecting Internal + External and refreshments Yes.
2. Invalid attendee email blocked progression. Organizer addresses and duplicates were counted once; nine people in an eight-seat room were rejected, while three people were accepted.
3. One final submission created a Pending request with the entered meeting information. Edit preserved mixed type, guest company and attendees, displayed the no-photo placeholder, and excluded its own occupied slot from availability.
4. Daily Friday 9 October through Tuesday 13 October previewed exactly Friday, Monday and Tuesday, skipping the weekend. Switching back to One meeting removed the additional dates from review.
5. All three steps were inspected at 390 × 844 after the mobile-grid correction; page width was 375 pixels, within the 390-pixel viewport. Desktop was inspected at 1500 × 1100 against the supplied layout reference.
6. A write probe in the isolated named `room_media` volume survived web-container recreation, then was removed. This establishes volume persistence for that local QA project; it is not a production photo backup/restore rehearsal.

### Existing laptop upgrade

The current local installation was backed up, rebuilt and migrated through 0009/0010. Pre/post counts matched: **five rooms, two bookings and three users**. Database, web and worker were healthy; `/healthz/` returned HTTP 200, and media storage was writable. The existing local file-email backend remained unchanged. Employee file-email login succeeded against the updated local instance; the desktop booking screen was captured at 1500 pixels, with no browser-console errors. Migration drift reported no changes; Git whitespace checks passed. QA was signed out/closed and the temporary viewport override was reset. These checks concern the laptop installation, not the company server.

The guides now cover all 45 configured routes, native-form fallback, real preview limitations, staff photo paths, media ownership/persistence, paired database/photo backups and migrations 0009/0010. Syntax checks of documented archive/extraction commands do not claim an executed photo restore. Actual staff photo upload is covered by integration tests; the browser review used existing rooms with no photo and does not claim a manual uploaded-photo walkthrough.

Company-server deployment of this release, actual mailbox delivery, employee-device behavior, representative load and a paired database/photo restore drill still require IT's acceptance checks. The local QA data and evidence do not establish those outcomes. Rebuild/recreate and migrate the company installation through the documented maintenance procedure; preserve existing database and media volumes.


## Per-room approval - 8 October 2026

This release adds Requires approval to staff room rows/add/edit and exposes Staff approval required or Automatic approval in employee room/booking screens. Migration `0011_room_requires_approval` follows 0010, defaults all existing rooms to checked and leaves saved booking status/history intact. Employee creations and substantive edits use the selected locked room policy; staff creation remains Approved. No-op saves and policy toggles do not convert an existing Pending queue.

### Automated verification

- Final PostgreSQL run: **281 tests passed in 43.153 seconds**, including 23 added booking-policy tests and 14 added staff-management tests. Django system checks reported no issues. The first run exposed an unchecked default on a new room form; it was corrected and the full suite rerun successfully.
- The complete migration chain through **0011** passed, including existing-data preservation. Tests exercise checked/unchecked creation and recurrence, selected-room edits, no-op retention, current policy under locks, normal validation/conflicts, confirmation/change mail, check-in link invalidation, approval metadata and audit. Staff tests cover verified access, CSRF, strict input, add/edit defaults, toggle persistence, retained booking states and audit.
- Full repository `ruff check .` and `ruff format --check .` passed (**77 Python files**). Node syntax checks for both application/wizard scripts passed. The Docker image build and collectstatic passed. No new company-server or live-SMTP result is implied.

### Actual browser checks

An isolated QA instance used local file email. Staff completed password-plus-email-code sign-in, unchecked Room 4 directly in Staff desk → Rooms, and the automatic POST persisted with the saved message. An employee completed email-link sign-in, selected that room and pressed **Confirm booking**: the resulting booking was **Approved**, identified as automatically approved. The same employee substantively edited it into checked Room 2: it became **Pending approval** with the earlier approval actor cleared. The staff checkbox screen was captured for the handover. These were real browser workflows; additional service/security edge cases are covered by tests rather than claimed as manual walkthroughs.

### Existing laptop upgrade and documentation

The laptop database was backed up in validated custom format, migrated through 0011 and web/worker recreated. Health returned HTTP 200; both services were healthy. Pre/post inventory matched: **five rooms, two bookings and three users**. Booking 1 remained Cancelled and booking 2 remained Pending; all five existing rooms defaulted to Requires approval checked. Local file email remained unchanged. No production server was accessed and no company email was sent.

Documentation now explains both room policies, checkbox auto-save/Save fallback, review queue retention, substantive/no-op edits, confirmation/check-in, recurrence, audit and migration 0011. The feature directory covers all **46 configured routes**. The HTTP update example builds before the outage, stops writers, takes paired database/media snapshots with database running, applies migrations/runtime grants, then recreates services. Documented command syntax/link checks validate examples; they do not claim the production update or photo restore has run.


## Invited meetings, attendee directory and professional email - 8 October 2026

This release changes My bookings to **My meetings** for organized and invited meetings, adds registered colleague suggestions/removable attendee chips, and redesigns authentication/event messages as branded multipart HTML with a plain-text alternative. Current attendee email controls read access; organizers and verified staff retain management permissions. Organizer-only Check in opens the existing confirmation GET/explicit POST flow. External recipients and former participants with neither current participation nor active staff access get Contact organizer; intentional change notices do not restore current read access or promise employee sign-in. No additional schema migration is required; **0011 remains the latest**.

### Automated verification

- Final clean PostgreSQL run: **323 tests passed in 39.242 seconds**; Django system checks reported no issues. This includes attendee visibility/authorization, directory-prefix responses and multipart-email regressions alongside the existing booking, recurrence, conflict, approval and check-in coverage.
- Tests cover current attendee case-insensitive detail/list/calendar/dashboard access, immediate loss after removal, organizer/attendee deduplication, unrelated privacy, attendee mutation denial, role/status/search/history filters and summary counts. Directory tests cover active approved-domain requester/results, GET-only/no-store, two-character threshold, 100-character bound, eight-result limit, prefix behavior and minimal email/name payloads.
- Email tests inspect plain-text plus HTML, inline CID wordmark, user-content escaping, authentication/setup messages, booking-event metadata, organizer-only check-in and deadline behavior, attendee exclusion, current revision/state supersession and external and removed-recipient contact actions. A service-level edit-flow regression removes an attendee and reassigns the organizer, then asserts delivery/action content for all six intended recipients: former participants get Contact organizer with no private check-in or dead View meeting promise, while current participants/active staff retain the appropriate action. These establish message construction and application behavior, not receipt in a company mailbox.
- Repository `ruff check .` and `ruff format --check .` passed for **81 Python files**. Node syntax checks passed for shared app, booking wizard and attendee picker scripts. Migration drift reported no changes; the committed graph still ends at 0011.

### Actual browser checks

An isolated local QA instance used file email and synthetic employee records; no company SMTP or production account was used. A separately signed-in employee in the Transgate domain saw their own meeting plus current Approved/Pending invitations in My meetings. The invited detail was read-only, role filtering worked, and the meeting page had no horizontal overflow at a **390-pixel** viewport. Organizer email showed the check-in action; attendee email omitted it. The HTML message also fitted the 390-pixel view.

The browser also exercised name-prefix suggestions, keyboard selection, bulk address addition/deduplication, chip removal, headcount changes and valid pending-input addition on Next. A newly submitted automatically approved booking persisted its selected attendees. Browser testing caught an asynchronous suggestion response overwriting an input-validation error; that behavior was fixed and the error was verified to remain visible until correction. The attendee picker was also checked at a 390-pixel mobile viewport with a 375-pixel document width and no horizontal overflow. Desktop meeting, attendee-picker and organizer-email previews were captured. Server edge cases and confirmation POST security are tested separately; this record does not claim a real company mailbox or manual check-in through a live relay.

### Laptop data and operational limits

Before the local update, a validated **82,877-byte custom-format PostgreSQL backup** was taken. After the rebuilt web/worker were recreated, database/web/worker were healthy, `/healthz/` returned HTTP 200, `check_worker_health` returned ok and Django system checks reported no issues. The existing inventory remained **five rooms, two bookings and three users**; local file-email settings were preserved. No production server was accessed and no company email was sent. This release requires rebuilt/recreated web and worker to load UI/API/mail changes, without reseeding records or replacing `.env`, database or photo volumes.

The maintained guides now cover all **47 configured routes**, organized/invited read versus management permissions, filter/count semantics, prefix suggestions/manual external addresses, chip behavior, multipart/CID rendering, organizer confirmation flow, external contact actions and targeted read-only troubleshooting. Syntax/link checks cover **13 Markdown documents, 113 local links, 94 Bash/sh blocks, 11 Python snippets and 12 PowerShell blocks**; those checks do not execute mutating deployment/retry examples. The printable handbook is regenerated from the maintained sources and its latest rendered pages are checked before handover.

Company-server deployment, actual HCL/other mail-client rendering and delivery, employee-device DNS/routing, load and recovery arrangements remain office acceptance checks. Local QA construction/screenshots and automated tests do not establish those outcomes.
