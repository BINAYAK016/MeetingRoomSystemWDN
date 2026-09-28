# Troubleshooting and testing

## Local development

- Run `docker compose ps` to check the database, web, and worker containers. Run `docker compose logs --tail=100 web worker db` for recent errors. `docker compose run --rm migrate` applies migrations after an update.
- `http://127.0.0.1:8000/healthz/` should return `ok`. If it returns 503, check PostgreSQL status and credentials in `.env`.
- Local mail is visible at `/dev/mail/` only for `127.0.0.1` or `localhost` with file mail mode. It is a development aid. Keep the same hostname while signing in; switching between `localhost` and `127.0.0.1` changes the cookie scope. If a CSRF page appears, reload sign-in and use a fresh form in the same browser session.
- `docker compose run --rm test` runs the PostgreSQL-backed test suite. It covers authentication, CSRF, reservation concurrency, recurrence, conflicts, no-show release, reminders, booking changes, staff access, and page rendering.

## Production

- Check `docker compose -f compose.prod.yaml ps`, then `logs --tail=100 web worker proxy db`. Confirm the TLS certificate matches the internal hostname and company devices trust its issuing CA.
- If sign-in emails are missing, verify `SMTP_HOST`, port, TLS setting, sender, and relay access. The worker handles booking notifications; employee login and staff codes send synchronously so a relay failure prevents authentication. Do not switch production to the local file mail backend.
- If check-ins are not releasing rooms, ensure the worker runs and inspect its logs. A stopped worker can delay release; booking creation and calendar requests also sweep due no-shows.
- If a booking conflicts, check room closures and the 15-minute gap in addition to the visible meeting period. The PostgreSQL exclusion constraint is the final overlap guard.
- If reports show low utilization, note that utilization counts only checked-in and completed meeting minutes. Cancelled and no-show meetings do not count as occupied use.

## Launch acceptance checklist

On the company pilot site, have Front Desk and selected employees verify all five real rooms, employee email sign-in, staff password plus code, room details, booking/create/edit/cancel, a simultaneous overlap attempt, attendee and Front Desk email notices, a one-hour reminder, secure check-in, automatic no-show release, room closure, reporting/Excel, audit log, TLS, backup, and a restore drill. Record issues before the company-wide rollout.
