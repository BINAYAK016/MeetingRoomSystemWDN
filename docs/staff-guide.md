# Front Desk and Administrator guide

Front Desk and Administrators have identical staff permissions. Sign in at `/staff/sign-in/` with your staff password, then enter the eight-digit code sent to your company email. The staff desk is separate from ordinary employee email-link sign-in. A staff account must first receive a password setup email from another staff member or IT's `create_staff_account` command.

## Daily work

- **Overview** shows upcoming meetings, today's no-shows, and failed email count. Open **Bookings** to search by meeting, room, or organizer and filter status, room, and date range. Results are paginated without discarding older records. Open a booking to see attendees, guest counts, refreshments, and preparation notes. You can edit confirmed future bookings, cancel active bookings, or manually check in during the check-in window.
- **Rooms** lets you add or edit rooms, facilities, instructions, seating capacity, and active status. Deactivate an unusable room; existing history is retained. **Closures** blocks a room for cleaning, maintenance, or another operational reason.
- **Rules** controls office hours, minimum/maximum duration, 15-minute slots, the gap between meetings, advance booking window, and check-in deadline. **Holidays** blocks company holidays unless staff create a booking with an override reason.
- **New booking** supports booking on behalf of an employee. Staff may enter an override reason for exceptional policy cases; the action is recorded in the audit log. Conflicting bookings are still prevented by PostgreSQL. Senior-management priority for the WDN third-floor room is coordinated manually by Front Desk.
- **People** lets staff search employees, edit their profile, activate/deactivate accounts, and grant/revoke staff access. Access changes revoke existing authentication sessions and pending sign-in challenges. Existing bookings retain their history and check-in links; cancel affected meetings separately when needed. You cannot remove your own staff access. Review staff access periodically. Use **Email setup link** for a new staff member or password reset; the link is one-time and expires after one hour.
- **Reports** offers common date ranges and custom periods up to one year, plus an Excel export with booking, room usage, department, and organizer sheets. Utilization estimates verified meetings’ scheduled time within current office hours, excluding weekends, holidays, and active closures. Historical rules/room activity are not reconstructed. **Audit log** is read-only, paginated, and filterable by action/actor.

Bookings and audit events remain in the database for at least one year; there is no automatic deletion job. IT should back up the database, monitor the worker and email relay, and perform periodic restore tests.

SMTP/email credentials must be supplied by the system administrator during production deployment. No production email credentials are included in this repository.
