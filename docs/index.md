# MBS complete documentation

**Transgate Tech | Binayak Bhandari**
**Reviewed:** 8 October 2026. **Application branch:** `mbs-prod`.

This is the documentation entry point for the existing Meeting Booking System: employee tasks, Front Desk/Administrator workflows, feature definitions, business examples, server operation, troubleshooting and recovery. It describes implemented behavior, including approval, rather than only the original requirements. The owner's later decisions take precedence over the questionnaire.

## Reading map

| Document | Audience | What it contains |
| --- | --- | --- |
| [Employee guide](user-guide.md) | Employees and organizers | Sign-in, rooms/calendar, three-step internal/external/mixed requests, individual/recurring meetings, edits, cancellation, check-in, profile and common questions. |
| [Staff guide](staff-guide.md) | Front Desk and Administrators | Password/email-code sign-in, dashboard, approval/rejection, rooms/photos, closures, on-behalf bookings, overrides, people, policy/holidays, reports and audit. |
| [Feature catalogue and use cases](features-and-use-cases.md) | Product owner, staff, testers and developers | Permissions, rules, lifecycle, notifications, detailed success/failure examples and supported limits. |
| [HTTP installation](deployment-http.md) | Linux operator | Selected Oracle Linux private-network installation, domain/IP/SMTP setup, build, migrations, initial staff and pilot. |
| [Operations runbook](operations-runbook.md) | Linux operator and IT | Configuration, background operation, updates, safe SQL/health checks, email recovery, backup scheduling, paired database/photo recovery, isolated restore and controlled live recovery. |
| [Troubleshooting and logs](troubleshooting.md) | Support and IT | Symptoms, exact diagnostic commands, safe log capture, CSRF, SMTP, Docker, DNS, worker, database, booking/report issues and laptop differences. |
| [Architecture](architecture.md) | Technical owner/developers | Components, transaction/occupancy design, authentication, privacy, worker, deployment and limitations. |
| [Database design](database-design.md) | Developers and database operators | Tables, relationships, constraints, statuses, indexes, runtime permissions and migration/rollback behavior. |
| [Verification report](verification-report.md) | Owner and reviewers | Historical/current test results, browser checks and isolated deployment/restore evidence; office pilot remains separate. |
| [Alternative HTTPS installation](deployment.md) | IT planning a future HTTPS change | Certificate-based profile, trust and deployment procedures. This is not the selected HTTP installation. |
| [Repository README](../README.md) | Laptop developers and new operators | Local Docker setup, configuration overview, builds and test commands. |

Read employees/staff first for everyday use. For a server incident, begin with troubleshooting's first-response commands. For a planned update/restore, read the operations procedure completely before executing it. Markdown command blocks are the authoritative copyable commands; the PDF is a printable companion.

## Current office installation

| Item | Selected configuration |
| --- | --- |
| Application | Meeting Booking System (MBS), Transgate branding, Times New Roman/system fallback |
| Site | [http://mbs.wdn.com.np](http://mbs.wdn.com.np) on the office network/VPN |
| Server | Oracle Linux 9.8, x86_64; office IP `192.168.50.222` |
| Repository/branch | [BINAYAK016/MeetingRoomSystemWDN](https://github.com/BINAYAK016/MeetingRoomSystemWDN/tree/mbs-prod), `mbs-prod` |
| Server checkout | `/opt/mbs/MeetingRoomSystemWDN` |
| Production Compose | `compose.prod.http.yaml` |
| Laptop Compose | `compose.yaml`; `http://127.0.0.1:8000/` |
| Employee domains | `wdn.com.np`, `transgate.com.np` |
| SMTP | `maildc01.wdn.com.np:25`, sender `mbs@wdn.com.np`, no relay username/password, TLS/SSL false |
| Timezone | `Asia/Kathmandu` for screens/rules; timezone-aware database instants |
| Staff role | Front Desk and Administrators have identical powers; individual accounts |

HTTP intentionally requires no certificate/private CA; browsers show **Not secure**. The selected profile still enforces production restrictions, CSRF, staff password plus email code, ownership and database conflict constraints. Keep access restricted to the approved office network/VPN. SMTP settings describe the previously accepted relay; new-server authorization and actual mailbox delivery must be checked on that installation.

## Rules and lifecycle at a glance

These are initial defaults, not immutable promises. Staff can change policy through the application; confirm current values before troubleshooting.

| Rule | Default |
| --- | --- |
| Working calendar | Monday-Friday, 09:00-17:00 Nepal time, excluding configured holidays |
| Meeting duration | 30-120 minutes |
| Start/end increment | 15 minutes |
| Gap after meeting | 15 minutes, counted once |
| Advance horizon | 14 days, including recurring occurrences |
| Recurrence | Daily/weekly/monthly; finite occurrences, no automatic future renewal |
| Employee request | Pending; holds the slot until review or expiry |
| Staff-created booking | Approved immediately |
| Unreviewed request | Cancelled at meeting start when reconciliation runs |
| Check-in | From start until before start + 15 minutes |
| No check-in | No show; occupancy released, history preserved |

Approved bookings edited in an employee session return to pending. Each recurring occurrence is reviewed separately and later edited/cancelled individually. Booking and closure conflicts share a PostgreSQL exclusion constraint. Staff overrides never allow simultaneous occupancy; WDN third-floor senior-management priority is handled manually.

## Where to go in the application

Append paths to `http://mbs.wdn.com.np`. Email-token URLs are generated by the system and must not be guessed/bookmarked/shared.

| Task | Path | Access |
| --- | --- | --- |
| Employee sign-in | `/sign-in/` | Allowed company email |
| Overview | `/` | Public landing page; workspace after sign-in |
| Rooms/directory | `/rooms/` | Signed-in user; no room-edit controls here |
| Calendar | `/calendar/` | Signed-in user; broader staff view |
| New booking/request | `/bookings/new/` | Signed-in user; staff can book on behalf |
| Own bookings | `/bookings/mine/` | Organizer's records |
| Profile | `/profile/` | Own names/department |
| Staff sign-in/code | `/staff/sign-in/`, `/staff/code/` | Active staff, password plus emailed code |
| Staff dashboard | `/staff/` | Verified staff |
| **Add/edit rooms** | `/staff/rooms/`, `/staff/rooms/new/`, `/staff/rooms/<room_id>/` | Verified staff; Edit link in room row |
| All bookings/pending | `/staff/bookings/`, `/staff/bookings/pending/` | Verified staff |
| Closures | `/staff/blocks/`, `/staff/blocks/new/` | Verified staff |
| Booking rules/holidays | `/staff/policy/`, `/staff/holidays/` | Verified staff |
| People/access/setup emails | `/staff/users/` | Verified staff |
| Reports/Excel | `/staff/reports/`, `/staff/reports.xlsx` | Verified staff |
| Audit | `/staff/audit/` | Verified staff |
| Health | `/livez/`, `/healthz/` | Read-only operational endpoints |
| Development email inbox | `/dev/mail/` | Loopback local file-mail only; unavailable in production |

The product's admin interface is **Staff desk**. There is no configured Django `/admin/` route. A staff account using employee email-link sign-in gets employee capabilities; use staff password/code sign-in for management.

## Quick operator commands (Linux)

All commands below use the selected production profile. Read the full guide for initial setup, schema updates and recovery.

```bash
cd /opt/mbs/MeetingRoomSystemWDN

# Read-only status and recent logs.
docker compose -f compose.prod.http.yaml ps -a
docker compose -f compose.prod.http.yaml logs --since 15m --tail=200 --timestamps web worker proxy db
curl --fail --show-error --max-time 15 http://mbs.wdn.com.np/healthz/

# Start already-installed services in the background.
docker compose -f compose.prod.http.yaml up -d web worker proxy

# Stop without deleting data (brief outage).
docker compose -f compose.prod.http.yaml stop proxy web worker

# Create a private database backup (writes a dump, does not stop the app).
COMPOSE_FILE=compose.prod.http.yaml sh deploy/backup.sh
```

Followed logs can be left with Ctrl+C without stopping services. If attached to interactive `docker compose up`, press **d** when its menu offers **Detach**; future starts should use `up -d`. Avoid `down --volumes`, global Docker pruning, direct SQL business-state edits and production test runs.

## Support boundaries and remaining operational decisions

The application includes configurable room records, finite recurrence, manual priority, approval, notifications, reports and audit; it does not include automatic monthly renewal, attendee personal-calendar conflict checks, ICS/HCL/Outlook integration, separate Front Desk permissions, attachments, a public REST API, high availability or automatic data-retention purging.

IT/company owners still choose backup destination/retention and acceptable recovery objectives, monitoring/log retention, actual room/holiday/policy records, priority procedures and pilot acceptance. Tests/rehearsals validate implementation; they cannot establish employee-device DNS, this server's relay authorization or company-wide readiness by themselves. No passwords, SMTP credentials or raw authentication links are included in these guides.

When behavior changes, update the relevant guides and regenerate the handbook with `python docs/build_handbook.py` using the optional documentation dependency. See [handbook build instructions](handbook-build.md).
