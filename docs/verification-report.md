# Verification report — 2 October 2026

## Scope and result

The existing Django/PostgreSQL application was reviewed and extended in place. Inspection covered templates/static assets, all URL routes and staff gates, authentication/session handling, forms and services, models/migrations, calendar and reporting queries, notification delivery, worker scheduling, Docker/HTTPS configuration, setup/backup commands, tests, and documentation.

The implementation is prepared for deployment with company configuration. The real company server, DNS, certificate trust, SMTP relay, backup destination, and representative office load have not been verified. No real SMTP credentials or test accounts are included in the repository, and no sample records are automatically loaded in production.

## Completed functionality and fixes

- Added an employee profile with name/department editing and server-side protection of identity/access fields.
- Completed room search by text, capacity, location, and facilities; retained details/availability and staff create/edit/deactivate/reactivate workflows.
- Added filtered, paginated bookings, users, audit history, and own upcoming/history views. Forms have useful validation, empty states, visible focus, and submission progress.
- Preserved finite daily/weekly/monthly recurrence, business rules, manual Front Desk priority, room closures, staff overrides with reasons, email check-in, automatic no-show release, and Excel reports.
- Corrected daily recurrence across weekends/holidays, stale room data during edits, first-time organizer races, and concurrent booking/edit/cancel lock ordering. PostgreSQL exclusion protection remains the final conflict guard.
- Calendar reflects database occupancy until actual release and labels past/closed/out-of-window slots unavailable. It groups calendar data once rather than repeatedly querying each cell.
- Corrected report utilization for working windows, holidays, room closures, partial/carry-in meetings, and interval unions. Historical utilization uses current policy and is documented as an estimate.
- Hardened email headers for long/newline meeting titles, added organizer check-in links to confirmation/change/reminder emails, recovered interrupted send leases, and added an audited retry command. Obsolete messages are superseded rather than falsely marked sent.
- Added disabled mail mode, explicit unavailable-delivery feedback, readiness/liveness, worker heartbeat, safe database errors, bounded dependency timeouts, and production runtime database permissions.
- Fixed stale migration images, proxy IP collisions, and Nginx routing after web container replacement.

## Security verified

- Employee one-time link and staff password/email-code flows; expiry, logout, replay prevention, safe GET previews, and CSRF-protected confirmation.
- Staff second factor cannot be bypassed through employee sign-in. Every staff route rejects employees/unverified staff; foreign booking IDs cannot disclose or modify another employee's booking.
- Atomic account/IP throttles and persistent one-time-code guess limits cannot be reset by changing sessions or client addresses. Only the trusted proxy supplies client-IP headers.
- Access changes invalidate all affected sessions and pending sign-in challenges, including after later reactivation. Password setup revalidates under locks and invalidates old challenges/sessions.
- Token records and pending session values contain hashes; public URLs reject stored digests. Queued email bodies necessarily contain check-in links, so database/backups remain access-controlled.
- Escaped HTML, literal Excel strings, same-origin CSP, frame denial, secure production cookies, no-store private responses, disabled debug, and logs without credentials/token URLs/exception values.
- Non-root, read-only production application containers; isolated database; separate runtime role without superuser/database/role/schema creation; runtime audit UPDATE/DELETE/TRUNCATE denied.

## Final automated gates

| Check | Result |
| --- | --- |
| Full suite from final immutable Docker image | **132 passed**, 19.028 seconds; clean test database creation and removal |
| Clean PostgreSQL migrations | Booking 0001–0007 and Django migrations succeeded |
| Simultaneous reservation tests | One same-slot booking succeeds; conflicting create/edit fails without partial records |
| Authentication concurrency tests | Single-use login/OTP/password setup, first-time account uniqueness, guess limits, access-change lock ordering passed |
| Email tests | Present/absent configuration, failures, zero delivery, retries, leases, reminders, long/newline subjects, and real SMTP backend against a localhost-only fake relay passed |
| Ruff lint / formatting | Passed; 56 Python files formatted |
| Python compilation | Passed for booking, config, and deployment scripts |
| Django system check | No issues |
| Migration drift | No changes detected |
| Production `check --deploy` | Completed; two expected warnings for HSTS subdomains/preload, documented in deployment guide |
| Dependency audit | No known vulnerabilities found in pinned application requirements at verification time |
| Docker build / static collection | Passed; 130 static files copied and fingerprinted |
| Static type checking | Not configured for this Django codebase; no type-check success is claimed |
| GitHub CI | Workflow added for the same lint/test/migration/audit/build gates; hosted runner execution is separate from this local verification |

Tests explicitly exercise rollback, backend authorization, inactive rooms, room reactivation, validation, booking ownership, conflicts with closures, buffer boundaries, recurrence, Nepal wall time, no-show/check-in races, safe failures/logs, profiles, paging, reports, and seed/bootstrap safeguards. Negative-path tests intentionally generate warning/error log messages; the suite completed successfully.

## Browser verification

Employee email-link confirmation completed without a CSRF error, including on the final image after token-session hardening. Profile save, booking creation/edit/cancellation, room filtering, calendar display, employee rejection at the staff URL, and logout were verified through the browser. Desktop, 390-pixel mobile, and 768-pixel tablet layouts were inspected; viewport overrides were reset. Room and booking forms did not overflow the viewport, and the final room screen produced no browser warning/error messages. Staff pages and mutations were exercised through the backend test client with verified staff sessions; real company mailbox-based staff sign-in remains a pilot check.

Browser records were confined to the existing local development database and file-email mode. The verification booking was cancelled and the temporary account deactivated; history/audit records were retained. Production rehearsal records were created only in a separate disposable project, which was removed after verification. The local application was stopped after verification, preserving database and local mail volumes.

## Isolated production rehearsal

A separate Compose project with synthetic secrets, an isolated database volume, a generated trusted localhost certificate, disabled mail, and a loopback HTTPS port was used. Verified:

1. Full fresh migrations, runtime role setup, and healthy HTTPS proxy/web/worker/database startup.
2. UID 1000 for application processes and read-only web/worker filesystems.
3. Runtime room/booking CRUD plus audit insertion; audit update/delete and schema creation denied.
4. Environment files, certificates, and backups absent from the image build context.
5. Database or stale/stopped worker produces safe HTTP 503 readiness; restored dependencies recover to HTTP 200.
6. Web container address replacement recovers through Docker DNS without proxy restart.
7. Actual `deploy/backup.sh` dump and `pg_restore --exit-on-error` succeeded. Restored counts matched users=1, rooms=1, reservations=1, notifications=6, audit=3, migrations=25.

Disposable containers, network, volume, certificate, secrets, and dump were removed. The existing local database volume was preserved. This rehearsal does not verify company network/certificate/SMTP behavior.

## Deployment package and exact process

Updated `Dockerfile`, `compose.yaml`, `compose.prod.yaml`, Nginx template, health scripts, environment examples/generator, database role setup, backup script, Git/Docker secret exclusions, and CI workflow. Preserved migrations 0001–0004 and added 0005–0007. README and architecture/database/user/staff/troubleshooting/deployment guides describe the complete system.

Follow [the deployment guide](deployment.md) for the exact first deployment, email enablement, initial staff setup, pilot checks, updates, monitoring, and restore commands. The sequence is:

1. Install Docker Engine/Compose and Git on the private Linux server; configure internal DNS, firewall/VPN access, and trusted TLS certificate/key.
2. Clone the repository and generate `.env` using `deploy/create-env.py --production`. Set the real host and matching HTTPS URL; protect `.env` and the certificate key. Keep email disabled until IT supplies the relay settings.
3. Validate Compose configuration, build the image, start PostgreSQL, run `migrate`, then run `db_setup`.
4. Start web/worker/proxy and verify HTTPS `/healthz/` returns 200.
5. Once SMTP is configured, recreate web/worker and run `create_staff_account approved.person@wdn.com.np`. The person completes password setup and password/email-code sign-in.
6. Enter real rooms/equipment/capacities, holidays, and approved booking rules. Verify employee/staff sign-in, room changes, booking/recurrence/conflicts, check-in/no-show, all mail, reports, and audit history on the company network.
7. Schedule backups to approved separate storage, verify a restore, and enable health/mail/disk/certificate/backup alerts before rollout.

Required production configuration: `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_APP_USER`, `POSTGRES_APP_PASSWORD`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `DJANGO_PUBLIC_BASE_URL`. Production Compose forces HTTPS and allows `wdn.com.np` and `transgate.com.np`. If its Docker subnet conflicts, update `PROXY_NETWORK_SUBNET`, `PROXY_NETWORK_DYNAMIC_RANGE`, `PROXY_IP`, and `AUTH_TRUSTED_PROXY_CIDRS` together.

SMTP configuration: `DJANGO_EMAIL_BACKEND=smtp`, `SMTP_HOST`, `SMTP_PORT`, `DJANGO_FROM_EMAIL`, `SMTP_USER`/`SMTP_PASSWORD` when required by the relay, and mutually exclusive `SMTP_USE_TLS`/`SMTP_USE_SSL`. Backend acceptance does not guarantee mailbox arrival; verify it with IT. The application starts with email disabled, but email-based sign-in requires delivery to be enabled before office use.

## Remaining operational limits

- Company server deployment, DNS/firewall/VPN, trusted certificate, actual SMTP/mailbox delivery, backup destination, and representative load must be verified when IT supplies configuration.
- One server remains a shared point of failure. Docker restarts exited processes; monitoring must alert on unhealthy running containers.
- Worker release is periodic, approximately 30 seconds plus at most one SMTP timeout after the deadline; ambiguous SMTP responses can cause duplicate delivery on retry.
- Utilization is based on current policy/holiday settings. Retention/purge scheduling remains an IT policy decision.
- Recurrence reserves only the approved booking horizon; later months are manually booked. HCL/Outlook integration is intentionally deferred.
- HSTS subdomain/preload policies stay disabled pending IT domain-wide approval. These are the only production Django check warnings.

SMTP/email credentials must be supplied by the system administrator during production deployment. No production email credentials are included in this repository.

## Employee domain update — 7 October 2026

Employee access now allows exactly `wdn.com.np` and `transgate.com.np` by default, including the production Compose configuration. Eligibility text and validation messages follow the configured domain allowlist.

All 139 application tests passed, including seven new tests for verified sign-in, booking organizers and attendees, staff setup, and rejection of unrelated or similar-looking domains. Test email delivery used local backends; delivery to real Transgate mailboxes still requires verification against the company's SMTP relay. Employee sign-in does not grant staff privileges.
