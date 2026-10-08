# Front Desk and Administrator guide

**Meeting Booking System (MBS)**
**Transgate Tech | Binayak Bhandari**
Checked against application source on **7 October 2026**.

Front Desk and Administrators have **identical permissions**. The custom staff desk is the administration interface at **http://mbs.wdn.com.np/staff/**; there is no exposed `/admin/` page. Employee booking screens remain available, but staff powers require password-plus-email-code verification. All displayed meeting dates/times use **Nepal time**.

Related documents: [employee guide](user-guide.md), [features/use cases](features-and-use-cases.md), [HTTP deployment](deployment-http.md), [troubleshooting and log commands](troubleshooting.md).

## Staff navigation

| Menu | Direct page | Main task |
| --- | --- | --- |
| Overview | [Staff desk](http://mbs.wdn.com.np/staff/) | Pending requests, meetings, no-shows, active rooms and failed mail |
| Pending requests | [Pending queue](http://mbs.wdn.com.np/staff/bookings/pending/) | Review earliest upcoming requests |
| Bookings | [Company bookings](http://mbs.wdn.com.np/staff/bookings/) | Search/filter all records and open management actions |
| Rooms | [Manage rooms](http://mbs.wdn.com.np/staff/rooms/) | Add/edit/deactivate rooms |
| Closures | [Room closures](http://mbs.wdn.com.np/staff/blocks/) | Block/release unavailable periods |
| Rules | [Booking rules](http://mbs.wdn.com.np/staff/policy/) | Office-wide booking/check-in policy |
| Holidays | [Company holidays](http://mbs.wdn.com.np/staff/holidays/) | Non-bookable dates |
| People | [People and access](http://mbs.wdn.com.np/staff/users/) | Profiles, active status, staff grants and setup email |
| Reports | [Usage reports](http://mbs.wdn.com.np/staff/reports/) | Date-range reports and Excel export |
| Audit log | [Action history](http://mbs.wdn.com.np/staff/audit/) | Read-only decisions and administration outcomes |

The top **Rooms** menu opens the employee directory. To find the room edit control choose **Staff desk → Rooms → Edit** in the room's row.

## 1. First access and staff sign-in

### Initial account setup

An existing verified staff member grants access in People, then sends a setup email. If no staff member can sign in, authorized IT uses this command **on the Linux server**, replacing the placeholder with the intended company mailbox:

```bash
cd /opt/mbs/MeetingRoomSystemWDN
docker compose -f compose.prod.http.yaml exec web python manage.py create_staff_account staff.member@wdn.com.np
```

This grants Active/Staff and sends a password setup link. It does not set a known/default password. It is intended for initial staff provisioning or authorized recovery, not bulk unreviewed access changes. Normal ongoing grants/revocations should use People.

1. Open the setup message in the intended mailbox.
2. Open its link within **one hour**.
3. Enter a password and matching confirmation, at least **12 characters**, passing the displayed password rules.
4. Save. The page directs you to staff sign-in.

**“Staff enabled, but setup email failed”** means access was granted even though the message failed. IT repairs delivery; the setup link can then be resent. Do not assume the failed command rolled back access.

### Normal sign-in

1. Open [Staff sign-in](http://mbs.wdn.com.np/staff/sign-in/).
2. Enter company email and password.
3. After the password stage succeeds, keep the code page open in that browser.
4. Read the newest **eight-digit** code in that mailbox, including any leading zeroes.
5. Enter it within **10 minutes** and submit.
6. Check that the staff Overview opens.

Up to five failed code attempts are allowed; expired/exhausted challenges require a fresh password stage. A new successful password challenge invalidates older codes. Password requests are limited to five per email and 30 per source IP per 15-minute window. Session lasts eight hours from successful sign-in.

Employee email-link sign-in does not verify staff powers; it can leave a staff member with an employee session. If the staff desk redirects you to sign-in, complete the password/code workflow. A password reset or access change can invalidate existing sessions. Sign out on shared devices.

### Password forgotten or setup expired

Ask another verified staff member to open **People**, find your active staff row and select **Email setup link**. Follow the one-hour link and set a new password. There is no public self-service password-reset form. If nobody has working staff access, IT uses the bootstrap command above after confirming the intended account.

## 2. Daily operating routine

1. Open **Overview** and check Pending requests, today's No shows and Failed emails.
2. Open **Pending requests** and review meetings before their start times.
3. Use **Bookings** to prepare for today's external guests, refreshments and equipment requests.
4. Open **Calendar** for day/week or staff-only month occupancy.
5. Monitor organizer check-in at meeting start; use Manual check-in only after confirming arrival and within the deadline.
6. Investigate failed mail with IT; missing reminders can cause missed check-ins even while meetings remain saved.
7. Review room closures and follow the company's manual senior-management priority process.

### What the overview numbers mean

| Indicator | Meaning |
| --- | --- |
| Pending requests | All records currently Pending; select card to review |
| Today's meetings | Approved, Checked in or Completed meetings with today's Nepal start date |
| Active rooms | Rooms marked Active |
| Today's no-shows | No show records with today's Nepal start date |
| Failed emails | Queued notifications currently Failed, including failures that may still be retrying |
| Upcoming meetings | Up to 12 future Approved meetings, earliest first |

The overview is refreshed when loaded, not a push-updated live monitor. A zero Failed emails number does not prove all mail reached inboxes; messages can be Pending, accepted by relay but filtered, or login/setup delivery can have failed outside the booking notification queue.

## 3. Review a Pending request

1. Open **Pending requests**. It lists earliest meeting start first, then request time.
2. Use room, search and date filters if needed; Reset removes them.
3. Select the meeting title to open detail.
4. Review requester, requested timestamp, room/date/time, department, attendee count, guest company, refreshments, description and Front Desk notes.
5. Choose Approve, Reject, Edit or Cancel as appropriate.

Pending requests already hold room/time, including the normal post-meeting gap. Approval does not compete for the slot again with another ordinary request. Check-in instructions are issued only after approval.

### Approve

1. Confirm the room/organizer remain active and the meeting has not started.
2. Press **Approve request** and confirm the prompt.
3. Check **Approved**, approval time and success message.

Approval records who approved it and queues confirmation to organizer, listed attendees and active staff. Only the organizer recipient gets its check-in link. If capacity, hours or holidays changed after request submission, review manually: approval does not revalidate every changed policy value.

### Reject

1. Enter a clear reason, for example **Please request the larger room for the client group**.
2. Press **Reject request** and confirm.
3. Check **Rejected** and the reason.

Reason is required and limited to 500 characters. The organizer sees it, the occupied interval is released and organizer/staff rejection messages are queued. Rejected records cannot be edited or approved again normally; the employee makes a new request.

### Expired/stale request

A request must be approved before its scheduled start. If still Pending at start, it is automatically Cancelled with an approval-window-expired reason. A stale page cannot approve a record already decided/cancelled or a meeting already started; reload and inspect status. Each recurring occurrence must be reviewed separately.

## 4. Search, edit, cancel and check in company bookings

### Find a booking

Open **Bookings** and filter by:

- Search: meeting title, organizer email or room name.
- Status, including Pending, Approved, Rejected, Checked in, Completed, Cancelled or No show.
- Room, including inactive rooms for historical records.
- From/To: inclusive Nepal meeting start dates.

General Bookings is latest meeting first; use filters for forthcoming work. Pagination keeps filters. Select a title for private detail. Verified staff can read all meeting notes/attendees; employees can only open their own organizer records.

### Edit

1. Open a **future Pending or Approved** record and select **Edit booking**.
2. Adjust fields, including room or organizer if appropriate.
3. Enter an override reason only if a justified rule exception is needed.
4. Save and inspect the result.

Staff edits to Approved retain Approved and queue change notices; staff edits to Pending keep Pending and require an explicit Approve action. An employee's substantive edit to Approved returns it to Pending and clears prior approval. An unchanged form save does not trigger a substantive status change.

Editing one series occurrence does not alter its siblings or recurrence pattern. Availability/capacity/current policy apply; failure leaves the saved booking intact. Old check-in links and stale pending notifications are superseded when substantive changes are saved. Removed attendees/former organizer receive change notices on an approved change.

### Cancel

1. Open an eligible Pending, Approved or Checked in booking.
2. Enter an explanatory cancellation reason, such as **Room needed for approved priority meeting; organizer informed**.
3. Press **Cancel booking** and confirm.
4. Verify Cancelled state and reason; check replacement arrangements separately.

The interval is released and history retained. Existing check-in links are invalidated; cancellation notifications are queued. There is no undo/bulk-series cancel action. Cancel each affected occurrence deliberately.

### Manual check-in

1. Confirm actual organizer/meeting arrival.
2. Open an Approved booking detail.
3. Within the configured check-in window, select **Manual check-in** and confirm.
4. Check Checked in state.

Default window is scheduled start through **before** start plus 15 minutes: a 10:00 meeting can be checked in at 10:00 but not at 10:15. The button may be visible before start; the server still rejects an early action. Manual check-in records your staff actor, invalidates email check-in tokens and queues check-in messages. No show records cannot be revived using it.

The worker normally reconciles every 30 seconds: Approved meetings missing the deadline become No show and release their intervals; checked-in meetings after end become Completed. Email failure does not extend the deadline. IT must investigate a delayed worker rather than changing timestamps directly.

## 5. Book on behalf and manage exceptions

1. From **Bookings**, select **Book for employee +**, or use **New booking** while in a verified staff session.
2. Fill meeting details as in the employee guide.
3. Enter **Organizer email** at `@wdn.com.np` or `@transgate.com.np`. Blank uses your own account.
4. An eligible email not already registered creates an employee account; an inactive organizer is rejected.
5. Enter an **Override reason** only for a justified exception.
6. Press **Create approved booking**.
7. Check Approved state and correct organizer; queued confirmation goes to that organizer/attendees/staff.

A newly created staff booking is Approved without the employee Pending stage. It still needs check-in. New recurring staff bookings create Approved occurrences; existing Pending requests remain Pending until explicitly approved.

### Exception behavior

A nonempty reason (maximum 500 characters) bypasses normal horizon, weekend/holiday, office-hour, duration and increment checks. For example: **Board meeting approved by Front Desk outside normal office hours**. It records the reason and the staff booking/change action.

The following cannot be bypassed:

- End after start and future start time.
- Active room and active eligible organizer.
- Room capacity calculation.
- Conflicts with bookings, Pending holds, closures and buffers.
- Recurring creation limits of 15 occurrences and at most 366 days.

The configured post-meeting gap still applies. The calendar normally marks closed times as unavailable even for staff; an approved exception is entered through the booking form.

### WDN third-floor senior-management priority

Priority is manual, with no automatic ranking/displacement. Review impacted meetings and communicate with organizers under company practice. Reject a Pending request, cancel an eligible meeting, or reschedule it to free the interval; then create the priority meeting. Put the explanation in the decision/cancellation reason and use an override reason if the replacement itself requires a rule exception. An override cannot occupy a still-held interval.

## 6. Add, edit or deactivate rooms

1. Open **Staff desk → Rooms**. This list contains active and inactive records.
2. Select **Add room +**, or **Edit** in an existing row.
3. Enter name, location, floor, positive seat capacity, description and room instructions.
4. Enter facility names separated by commas, semicolons or newlines, such as **Projector, Whiteboard, Video conferencing**.
5. Select **Active** to offer it for bookings; clear Active to retire it.
6. Save and check **Room saved**, updated row and employee directory when appropriate.

Example: name **Room 1**, location **Kantipat**, floor **3**, capacity **8**, instructions **Leave the room tidy and switch off the projector**. Use actual office data; example rooms are not automatically imported into production.

Name/location/floor must be unique together. Capacity must be positive. Facilities are free-text descriptive labels, up to 50 names and 120 characters each, deduplicated without case sensitivity. Description/instructions allow up to 10,000 characters. Changing a facility label changes search choices; it does not allocate inventory.

Deactivation prevents new selection/approval and removes the room from employee calendars/directory. It preserves records and does **not** cancel existing Approved meetings. Review them first and cancel/reschedule affected occurrences separately. Capacity/description changes do not rewrite or cancel old reservations. There is no room delete button; preserving the record keeps historical links intact.

## 7. Block or release unavailable periods

### Add a closure

1. Open **Closures → Block room +**.
2. Choose active room, future date and start/end.
3. Enter reason, for example **Projector replacement**.
4. Save and verify Blocked state and calendar occupancy.

Closures reserve exactly the chosen interval and do not add the meeting buffer. They require future start and end after start, on one date. They cannot overlap any active hold/booking/closure; resolve impacted bookings before blocking. Normal meeting horizon, office-hours, working-day, duration and server slot checks are not applied to closures. For a multi-day closure, add one entry per day.

### Remove a closure

1. Find it under **Closures**.
2. Select **Remove** and confirm.
3. Check **Closure cancelled** and the released interval.

The record stays in closure history. There is no closure time-edit form; remove/recreate when a period changes. Review the calendar before assuming the removed period is available, because another reservation can occupy it.

## 8. Change booking rules

1. Open **Rules**.
2. Review existing values before editing; there is one office-wide policy.
3. Enter approved changes and save.
4. Check **Booking rules saved** and notify affected employees through office practice.
5. Review existing requests/meetings that could be affected.

| Field | Initial value | Allowed form range / relationship |
| --- | --- | --- |
| Opens at / Closes at | 09:00 / 17:00 | Ordered times aligned to configured increments |
| Minimum minutes | 30 | 1–1440; fits office hours; whole increments |
| Maximum minutes | 120 | 1–1440; at least minimum; whole increments |
| Slot minutes | 15 | 1–60 |
| Gap minutes | 15 | 0–120; appended after each meeting |
| Advance days | 14 | 1–366 |
| Check-in minutes | 15 | 1–1440 and no greater than minimum meeting duration |

Example: keeping 15-minute slots and changing maximum from 120 to 180 is a valid whole-increment value if approved by office policy. Setting minimum to 20 with 15-minute increments is invalid; opening after closing is invalid. Working weekdays are fixed Monday–Friday in code and are not editable here.

Changed rules apply to new/edited bookings. Existing occupied buffers remain their stored values; changing the gap does not rebuild them. Check-in uses the **current** deadline when confirming and releasing meetings, so shortening it can affect already Approved meetings. Adding holidays/changing hours does not automatically cancel old bookings. Reports also use current rule assumptions, which can change historical utilization estimates.

## 9. Manage company holidays

1. Open **Holidays**.
2. Enter date and name, for example **Company holiday**.
3. Save. An existing date updates that holiday's name rather than adding a duplicate.
4. Review scheduled bookings on that date and handle them separately if needed.
5. To remove an entry, use its **Remove** action; the removal is audited.

Dates must be valid and name is required (up to 160 characters). Holiday entries are unique by date. Daily normal recurrence skips these dates; weekly/monthly series containing a holiday are rejected unless staff enters an exception. Existing meetings are not automatically cancelled. Removing a holiday does not open weekends, which remain closed independently.

## 10. Manage people and access

### Add/update an employee

1. Open **People**.
2. Enter an eligible company email, names and department.
3. Select **Active account** for normal employee sign-in.
4. Select **Front Desk / Administrator access** only for staff who need full management powers.
5. Save and check the directory row.

Use Search for email/name/department and filter Everyone, Staff or Inactive. **Edit employee** loads an existing person's values into the form; **Clear form** returns to a new-entry form. Email is the lookup identity. Changing it creates/updates the account at the new address, rather than renaming the original account. Contact IT for an email-identity migration that must preserve ownership history.

### Grant staff and send setup

1. Save the person with both Active and Front Desk / Administrator selected.
2. In that active staff row, select **Email setup link**.
3. Confirm **Password setup link sent**.
4. Ask the person to check their mailbox and complete the one-hour setup.

Saving staff access does not automatically send this email. The button sends directly through SMTP; a failure appears as **The setup email could not be sent**. It does not revert the access flag. It can also send a fresh reset link for an existing password.

### Revoke or deactivate

1. Review future meetings and cancel/reassign them separately where necessary.
2. Find the person and select **Edit employee**.
3. Clear Staff to keep an active employee without management powers, or clear Active to prevent normal account access.
4. Save and check row status.

An access change invalidates existing login sessions and pending sign-in challenges. Password changes invalidate existing sessions as well. Records/bookings/audit history remain; account deactivation does not cancel bookings automatically. You cannot remove your own staff role or deactivate your own account through People. There is no separate administrator-only permission tier or grant approval chain.

## 11. Generate reports and export Excel

1. Open **Reports**.
2. Choose Today, This week, This month, This quarter or This year, or set From/To.
3. Press **Show report**. End points are inclusive Nepal meeting start dates; preset ends are today.
4. Read total booking records, room usage, department and organizer tables.
5. Select **Download Excel** for the same range.

Custom end minus start may span at most 366 days. Reversed/excessive ranges produce a message and today fallback on the page; invalid Excel requests are rejected. Default is current month's first day through today.

### Interpret the numbers

- Booking counts include all statuses, such as Pending, Rejected, Cancelled and No show, and use meeting start date. Closures are not counted as meetings.
- Department/organizer counts include those same records. Blank department is Unspecified.
- Room rows include inactive rooms; most booked rooms appear first.
- Utilization counts checked-in/completed **scheduled minutes** clipped to current working hours minus current holidays/active closures. It does not count buffers, merely Approved time, or No shows.
- A checked-in meeting contributes its full scheduled interval, even before it finishes. This is not an actual attendance/early-departure measurement.
- Policy, holiday, closure and room activation history are not reconstructed. Historical percentages can change when current policy changes.
- The denominator is the full selected range; future dates add available hours. Use a completed or appropriate period for meaningful comparison.

Example under default rules: one room has 480 bookable minutes on a normal weekday. A checked-in 60-minute meeting contributes 12.5% utilization; a Pending request adds to booking count but not utilized minutes. Closures reduce the denominator by their overlap with working hours. Real percentages depend on current holidays/closures/range.

Excel contains **Bookings**, **Room usage**, **Departments** and **Organizers** sheets, with headers, filters and frozen first row. Booking rows include ID/date/start/end/room/organizer/department/status/title. Notes, full attendee lists, authentication tokens and audit records are not exported. Excel is a report, not a backup.

## 12. Use audit history

1. Open **Audit log**.
2. Select an action, for example `booking_approved`, `booking_modified`, `user_access_modified` or `room_modified`.
3. Optionally enter actor-email search.
4. Press **Filter** and inspect timestamp, actor, target type/ID and outcome.
5. Use Reset to clear filters; page through older events.

The UI is read-only and displays 50 events per page. “System” means no actor was attached to that automated/anonymous event. Audit supports investigation of booking decisions, access/password actions, room/rule/holiday changes and selected sign-in/mail failures. It does not log every page view, provide full email bodies or replace IT's service logs. There is no UI audit delete/export button or automatic one-year purge.

## 13. Email issues and escalation

Booking events are queued independently of saved reservation transactions. Login links, staff codes and setup messages are sent directly during the request, so their failure may appear in audit/logs rather than the Failed emails dashboard count.

For queued booking mail, the worker attempts at most five deliveries, with backoff. Some Failed messages are awaiting automatic retry; exhausted failures need authorized IT retry after repairing the cause. Obsolete messages are superseded when bookings change. Relay acceptance is not proof of final mailbox delivery.

If users report missing mail:

1. Confirm current booking state and correct organizer/attendee addresses.
2. Check dashboard Failed emails; do not conclude delivery succeeded from a zero count alone.
3. Ask IT to inspect SMTP, worker heartbeat and queue using [troubleshooting commands](troubleshooting.md).
4. If the meeting has started and attendance is verified, perform Manual check-in **before** its deadline when needed.
5. Do not promise the system will extend the deadline during an email outage.

Record ordinary page/action, approximate Nepal time, booking ID and visible error/request reference if present. Keep passwords, email codes, token-bearing links and `.env` contents private. Direct HCL/Outlook calendar sync is deferred; missing entries in those calendars are not evidence of failed MBS confirmation delivery.

## 14. Handover and retention

Front Desk owns review, guest/preparation requests, manual priority arrangements, room records and appropriate access changes. IT owns server/worker/mail health, database credentials, backups/restores, Docker updates, logs/disk monitoring and technical incident diagnosis. Staff should escalate service errors rather than change database rows to bypass workflows.

Keep booking/audit history under the approved company retention policy, including any requirement to retain at least one year. The application currently has no automatic retention purge. Room inactivity, account inactivity and cancelled reservations retain their history. See [deployment](deployment-http.md) and [troubleshooting](troubleshooting.md) for maintenance, diagnostics and recovery commands.
