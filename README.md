# Meeting Room Booking System

An internal office application under development. This first module provides the PostgreSQL schema, Django project, Docker Compose setup, and a shared reservation write path. Employees cannot book through a screen yet. The next module will add email identity, followed by room management and booking workflows. See [database design](docs/database-design.md) for the ERD and constraints.

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

## Development order

1. Database schema and Docker foundation (this module).
2. Employee email sign-in and staff authentication.
3. Room management.
4. Booking and availability calendar, including recurrence and check-in.
5. Notifications, reports, audit views, pilot tests, and production deployment.
