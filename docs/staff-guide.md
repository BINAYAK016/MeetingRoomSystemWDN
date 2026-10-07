# Front Desk and Administrator guide

**Transgate Tech | Binayak Bhandari**

Front Desk and Administrators have identical permissions. Sign in at `/staff/sign-in/` with a password, then the eight-digit company-email code. Ordinary employee email-link sign-in does not unlock staff powers. IT or an existing verified staff member sends the initial one-time password setup link.

## Review booking requests

Open **Pending requests** from the staff desk. Review the requester, room, date, start/end, title, notes, attendees, request timestamp, and status on the detail page. Pending requests already hold their slots.

- **Approve** changes a future pending request to **Approved**, records who approved it and when, and queues confirmation and check-in instructions.
- **Reject** requires a reason. The request becomes **Rejected**, the reason is visible to its owner, the slot is released, and a rejection notice is queued.
- **Cancel** releases eligible pending or approved bookings while retaining their history and cancellation reason.

Approval/rejection actions require a verified staff session and a CSRF-protected POST. A stale page cannot approve a cancelled/rejected request. Requests still pending at the meeting start expire automatically. Review each recurring occurrence separately. Employee changes to approved meetings require approval again; staff edits to approved meetings retain approval; edits to pending requests keep them pending and issue updated instructions.

## Daily work

- **Overview** shows pending requests, upcoming meetings, no-shows, and failed email. **Bookings** searches meeting, room, or organizer and filters status, room, and date. Open details for attendees, guests, refreshments, and notes. Edit eligible future bookings or check in manually during the valid window.
- **Rooms** adds/edits name, location, floor, capacity, equipment, instructions, and active status. Deactivation prevents new bookings and approval but preserves history; review affected existing bookings separately. **Closures** reserves unavailable periods and cannot overlap occupied requests or meetings.
- **Rules** controls working hours, duration, slots, gap, booking horizon, and check-in deadline. **Holidays** manages non-bookable dates. Staff exceptions require a recorded override reason.
- **New booking** creates an approved booking on behalf of an employee. Policy exceptions remain audited and cannot bypass overlap constraints. Front Desk handles WDN third-floor senior-management priority manually.
- **People** searches employees, edits names/department, activates/deactivates accounts, and grants/revokes staff. Access changes revoke existing sessions and pending sign-in challenges. Booking history stays intact; cancel affected meetings separately. You cannot remove your own staff access. **Email setup link** sends a one-time password setup/reset link valid for one hour.
- **Reports** supports common or custom ranges up to one year, with Excel booking, room, department, and organizer sheets. Utilization counts checked-in/completed time within current working hours, excluding holidays and closures. Historical policy is not reconstructed. **Audit log** is read-only and filterable by actor/action.

Notification delivery is queued separately from booking transactions. Disabled SMTP leaves jobs pending; failed jobs retry and remain visible. After IT repairs delivery, use the audited `retry_failed_mail` command for eligible exhausted failures. Backend acceptance does not prove mailbox arrival.

Keep booking/audit history for at least one year under company retention policy. IT must monitor worker, failed mail, service health, disk, certificates, backups, and tested restores.

SMTP credentials must be supplied separately during production deployment. No production email credentials are included in this repository.
