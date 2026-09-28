# Meeting Room Booking System

An internal office application under development. The completed modules provide the PostgreSQL schema, Docker Compose setup, a shared reservation write path, and employee sign-in using one-time links sent to `wdn.com.np` addresses. Employees cannot book through a screen yet. See [database design](docs/database-design.md) for the ERD and constraints.

## Why this structure

One Django application runs the web process and, in later modules, scheduled commands. PostgreSQL stores rooms, bookings, email jobs, and audit data. A shared `reservations` table and PostgreSQL exclusion constraint prevent bookings and room closures from occupying the same room at overlapping times. The application also locks the room row before writing, so concurrent requests return a clear conflict. The database remains the final guard.

## Local setup on Windows PowerShell

Docker Desktop with its Linux engine must be running. Run these commands inside this repository folder:

```powershell
Copy-Item .env.example .env
python -c 'import secrets; from pathlib import Path; p=Path(".env"); t=p.read_text(); t=t.replace("POSTGRES_PASSWORD=\n", "POSTGRES_PASSWORD="+secrets.token_urlsafe(36)+"\n"); t=t.replace("DJANGO_SECRET_KEY=\n", "DJANGO_SECRET_KEY="+secrets.token_urlsafe(60)+"\n"); p.write_text(t)'
docker compose build
docker compose up -d db
docker compose run --rm migrate
docker compose up -d web
Invoke-WebRequest http://127.0.0.1:8000/healthz/
```

`Copy-Item` creates a local configuration file. The Python command generates random local passwords and keys in that file; `.env` is ignored by Git. `docker compose build` packages the Django application. `up -d db` starts PostgreSQL and keeps its data in a Docker volume. `run --rm migrate` applies committed database migrations. `up -d web` starts the web process. The last command checks that the application can reach PostgreSQL and should return `ok`.

To run the database and concurrency tests:

```powershell
docker compose run --rm test
```

To load five clearly labelled **demo rooms** into a local database only:

```powershell
docker compose run --rm web python manage.py loaddata demo_rooms
```

To stop local containers while preserving database data:

```powershell
docker compose down
```

The `web` port is bound to `127.0.0.1` for local use. Production deployment will add the company hostname, HTTPS reverse proxy, server-specific settings, backups, email relay, staff authentication, and operational monitoring. Do not publish the current foundation as a finished booking service.

## Employee sign-in module

Open `http://127.0.0.1:8000/`, then enter a `wdn.com.np` address. A link is valid for 15 minutes and can be used once. Opening it leads to a confirmation button; the account is created and signed in only after that button is pressed. Other domains, inactive accounts, and repeated requests receive the same public response. The current limit is three links per address in 15 minutes. Sign-in tokens are stored as hashes.

For local testing, the default email backend writes messages inside the running web container. To list and read the newest local message:

```powershell
docker compose exec web sh -c 'ls -t /tmp/meeting-room-mail | head -1'
docker compose exec web sh -c 'cat /tmp/meeting-room-mail/$(ls -t /tmp/meeting-room-mail | head -1)'
```

These messages are development data and disappear if the web container is replaced. When IT supplies the SMTP relay, set `DJANGO_EMAIL_BACKEND=smtp`, `DJANGO_FROM_EMAIL`, `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD`, and `SMTP_USE_TLS` in the server's `.env`. Production HTTPS mode requires SMTP. Configure the HTTPS proxy to omit `/sign-in/link/` paths from access logs because they contain one-time secrets. Employee email login does not authorize staff operations; the staff MFA gate is a later module.

## Development order

1. Database schema and Docker foundation (done).
2. Employee email sign-in (done).
3. Staff authentication and room management.
4. Booking and availability calendar, including recurrence and check-in.
5. Notifications, reports, audit views, pilot tests, and production deployment.
