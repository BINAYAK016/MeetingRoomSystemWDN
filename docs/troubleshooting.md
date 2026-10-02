# Troubleshooting and testing

## Local development

- Run `docker compose ps` to check the database, web, and worker containers. Run `docker compose logs --tail=100 web worker db` for recent errors. `docker compose run --rm migrate` applies migrations after an update.
- `http://127.0.0.1:8000/healthz/` should return a JSON status of `ok` after web and worker start. HTTP 503 identifies an unavailable database or stale/missing worker. `/livez/` checks only the web process.
- Local mail is visible at `/dev/mail/` only for `127.0.0.1` or `localhost` with file mail mode. It is a development aid. Keep the same hostname while signing in; switching between `localhost` and `127.0.0.1` changes the cookie scope. If a CSRF page appears, reload sign-in and use a fresh form in the same browser session.
- `docker compose run --rm test` runs the PostgreSQL-backed test suite. It covers authentication, CSRF, reservation concurrency, recurrence, conflicts, no-show release, reminders, booking changes, staff access, and page rendering.

## Production

- Check `docker compose -f compose.prod.yaml ps`, then `logs --tail=100 web worker proxy db`. Confirm the TLS certificate matches the internal hostname and company devices trust its issuing CA.
- Disabled or incomplete SMTP configuration logs a warning and permits startup, but email sign-in is unavailable and notifications remain pending. Supply `SMTP_HOST`, `SMTP_PORT`, `DJANGO_FROM_EMAIL`, optional authenticated-relay `SMTP_USER`/`SMTP_PASSWORD`, and exactly one of STARTTLS (`SMTP_USE_TLS`) or implicit TLS (`SMTP_USE_SSL`) when required. Set `DJANGO_EMAIL_BACKEND=smtp` and recreate web/worker. The worker handles booking notifications; employee login and staff codes send synchronously so a relay failure prevents authentication. The local file backend is rejected over HTTPS.
- If check-ins are not releasing rooms, ensure the worker is healthy and inspect its logs. A stopped worker can delay release; booking writes also reconcile due no-shows, while calendar GET requests hide overdue reservations without changing records. The worker reconciles roughly every 30 seconds with at most a ten-second SMTP send between cycles.
- If a booking conflicts, check room closures and the 15-minute gap in addition to the visible meeting period. The PostgreSQL exclusion constraint is the final overlap guard.
- If reports show low utilization, note that utilization counts only checked-in and completed meeting minutes. Cancelled and no-show meetings do not count as occupied use.
- After production migrations, run `docker compose -f compose.prod.yaml run --rm db_setup` to grant the runtime role access to new tables. Preserve existing database administrator credentials and volume; PostgreSQL initialization environment variables do not reset passwords on an existing volume.
- Docker marks stale worker, database, web, or proxy health checks unhealthy; restart policies act only when a container exits. Alert on health status and investigate logs before restarting repeatedly.

SMTP/email credentials must be supplied by the system administrator during production deployment. No production email credentials are included in this repository.

## Launch acceptance checklist

On the company pilot site, have Front Desk and selected employees verify all five real rooms, employee email sign-in, staff password plus code, room details, booking/create/edit/cancel, a simultaneous overlap attempt, attendee and Front Desk email notices, a one-hour reminder, secure check-in, automatic no-show release, room closure, reporting/Excel, audit log, TLS, backup, and a restore drill. Record issues before the company-wide rollout.
