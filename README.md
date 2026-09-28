# WDN Meeting Rooms

An internal meeting room application for `wdn.com.np` employees. Django, PostgreSQL, and Docker Compose power the application. The interface uses the Transgate palette and logo, with Times New Roman until a licensed web font is available.

## Features

- Employee sign-in by one-time company email link.
- Front Desk and Administrator access with a password and one-time email code. Both staff roles have the same permissions.
- Room directory, day/week availability, and staff month view.
- Booking, editing, and cancellation, with 15-minute time slots and a configurable gap. PostgreSQL prevents overlapping reservations, including room closures.
- Daily, weekly, and monthly recurrence within the two-week booking window. Later monthly meetings are booked manually.
- Email confirmation, change, cancellation, one-hour reminder, check-in, and no-show notices.
- Organizer email check-in link after meeting start; a worker releases missed check-ins at the 15-minute deadline.
- Staff management of rooms, closures, holidays, booking rules, employees, and access. Booking on behalf of an employee and policy override with a recorded reason are supported.
- Audit history and room/department reports with Excel download.

Direct HCL/Outlook calendar integration is planned after the first launch, as agreed. WDN third-floor senior-management priority is handled by Front Desk manually.

## Run locally

Install Docker Desktop and use its Linux engine. In PowerShell, from this repository:

```powershell
Copy-Item .env.example .env
python -c 'import secrets; from pathlib import Path; p=Path(".env"); t=p.read_text(); t=t.replace("POSTGRES_PASSWORD=\n", "POSTGRES_PASSWORD="+secrets.token_urlsafe(36)+"\n"); t=t.replace("DJANGO_SECRET_KEY=\n", "DJANGO_SECRET_KEY="+secrets.token_urlsafe(60)+"\n"); p.write_text(t)'
docker compose build
docker compose up -d db
docker compose run --rm migrate
docker compose up -d web worker
Invoke-WebRequest http://127.0.0.1:8000/healthz/
```

Open <http://127.0.0.1:8000/>. Enter a `wdn.com.np` address; the local test inbox at <http://127.0.0.1:8000/dev/mail/> shows its one-time link. This inbox is a developer convenience and does not prove mailbox ownership. Live use requires the company's SMTP relay.

Optional sample data: `docker compose run --rm web python manage.py loaddata demo_rooms`. These five rooms are labelled demos; replace them with real room details before a pilot.

For a local staff account, run `docker compose exec web python manage.py create_staff_account your.name@wdn.com.np`, then open the password setup link in the local test inbox. Staff sign-in at `/staff/sign-in/` emails an eight-digit code to the same inbox. In production, IT should run this command for the two named Administrators and Front Desk accounts after SMTP is configured.

Tests: `docker compose run --rm test`. To stop containers while keeping PostgreSQL data: `docker compose down`.

## Production deployment

See [deployment guide](docs/deployment.md). The production Compose file serves HTTPS through Nginx, keeps PostgreSQL off host ports, runs the booking worker, and requires SMTP. IT must supply the private Linux server, internal hostname and DNS, TLS certificate/key, SMTP relay details, and approved initial staff email addresses. These have not yet been supplied, so this repository has not been deployed on the company network.

Guides: [employee use](docs/user-guide.md), [Front Desk and Administrator use](docs/staff-guide.md), [troubleshooting and pilot checks](docs/troubleshooting.md), [architecture](docs/architecture.md), and [database design](docs/database-design.md).

## Operations

The worker checks every 30 seconds for due reminders, email delivery, meeting completion, and missed check-ins. Pending emails are stored in PostgreSQL and retried after transient failures. Staff can see the count of failed messages on the staff dashboard. Run `docker compose -f compose.prod.yaml logs -f web worker proxy` for service logs.

The production backup script is [deploy/backup.sh](deploy/backup.sh). Schedule it from the Linux host, keep backup files outside the server as required by company policy, and test restore before launch.
