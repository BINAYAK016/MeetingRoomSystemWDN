# Front Desk and Administrator guide

Front Desk and Administrators have identical staff permissions. Sign in at `/staff/sign-in/` with your staff password, then enter the eight-digit code sent to your company email. The staff desk is separate from ordinary employee email-link sign-in. A staff account must first receive a password setup email from another staff member or IT's `create_staff_account` command.

## Daily work

- **Overview** shows upcoming meetings, today's no-shows, and failed email count. Open **Bookings** to search by meeting, room, or organizer and filter status. Open a booking to see attendees, guest counts, refreshments, and preparation notes. You can edit, cancel, or manually check in a booking as needed.
- **Rooms** lets you add or edit rooms, facilities, instructions, seating capacity, and active status. Deactivate an unusable room; existing history is retained. **Closures** blocks a room for cleaning, maintenance, or another operational reason.
- **Rules** controls office hours, minimum/maximum duration, 15-minute slots, the gap between meetings, advance booking window, and check-in deadline. **Holidays** blocks company holidays unless staff create a booking with an override reason.
- **New booking** supports booking on behalf of an employee. Staff may enter an override reason for exceptional policy cases; the action is recorded in the audit log. Conflicting bookings are still prevented by PostgreSQL. Senior-management priority for the WDN third-floor room is coordinated manually by Front Desk.
- **People** lets staff activate/deactivate employee accounts and grant/revoke staff access. Review staff access periodically. Use **Email setup link** for a new staff member or password reset; the link is one-time and expires after one hour.
- **Reports** offers common date ranges and custom periods up to one year, plus an Excel export with booking, room usage, department, and organizer sheets. **Audit log** shows recent sign-ins and administrative activity.

Bookings and audit events remain in the database for at least one year; there is no automatic deletion job. IT should back up the database, monitor the worker and email relay, and perform periodic restore tests.
