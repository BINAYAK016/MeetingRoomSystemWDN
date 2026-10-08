# Front Desk and Administrator guide

**Meeting Booking System (MBS)**
**Transgate Tech | Binayak Bhandari**
Checked against application source on **8 October 2026**.

Front Desk and Administrators have **identical permissions**. The custom staff desk is the administration interface at **http://mbs.wdn.com.np/staff/**; there is no exposed `/admin/` page. Employee booking screens remain available, but staff powers require password-plus-email-code verification. All displayed meeting dates/times use **Nepal time**.

Related documents: [employee guide](user-guide.md), [features/use cases](features-and-use-cases.md), [HTTP deployment](deployment-http.md), [troubleshooting and log commands](troubleshooting.md).

## Staff navigation

| Menu | Direct page | Main task |
| --- | --- | --- |
| Overview | [Staff desk](http://mbs.wdn.com.np/staff/) | Pending requests, meetings, no-shows, active rooms and failed mail |
| Pending requests | [Pending queue](http://mbs.wdn.com.np/staff/bookings/pending/) | Review earliest upcoming requests |
| Bookings | [Company bookings](http://mbs.wdn.com.np/staff/bookings/) | Search/filter all records and open management actions |
| Rooms | [Manage rooms](http://mbs.wdn.com.np/staff/rooms/) | Add/edit/deactivate rooms |
| Departments | [Manage departments](http://mbs.wdn.com.np/staff/departments/) | Add, rename, activate or deactivate booking/profile options |
| Closures | [Room closures](http://mbs.wdn.com.np/staff/blocks/) | Block/release unavailable periods |
| Rules | [Booking rules](http://mbs.wdn.com.np/staff/policy/) | Office-wide booking/check-in policy |
| Holidays | [Company holidays](http://mbs.wdn.com.np/staff/holidays/) | Add dates manually or preview/confirm an Excel holiday schedule |
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
4. Open **Calendar** for Month/Week/Day occupancy, filter by room and follow meeting cards. Verified staff can open all booking details; employee month cards retain normal privacy.
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

General Bookings is latest meeting first; use filters for forthcoming work. Pagination keeps filters. Select a title for private detail. Verified staff can read all meeting notes/attendees. Employees can read meetings they organize or are currently invited to; attendee sessions cannot edit/cancel/review or receive organizer check-in rights.

### Edit

1. Open a **future Pending or Approved** record and select **Edit booking**.
2. Adjust fields, including room or organizer if appropriate.
3. Enter an override reason only if a justified rule exception is needed.
4. Save and inspect the result.

Staff edits to Approved retain Approved and queue change notices. A substantive staff edit to Pending keeps it Pending when the selected room requires approval; when the room is unchecked, it becomes Approved automatically and queues confirmation. An employee's substantive edit follows the selected room's current policy: checked means Pending with prior approval cleared, unchecked means Approved automatically. An unchanged form save retains the state, even if a Pending request's room was unchecked after submission.

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
2. Complete **Schedule & details** as in the employee guide: date/duration/start, an available room, title, type, department, purpose, refreshments and special requirements. External and Internal + External meetings require a guest company.
3. For a justified policy exception, open **Staff booking options** and enter **Booking rule override reason**. Use custom/manual times for an exceptional schedule; preview and saving still enforce non-bypassable rules.
4. In **Attendees**, enter **Book on behalf of an employee** at `@wdn.com.np` or `@transgate.com.np`. Blank uses your own account. An eligible email not already registered creates an employee account; an inactive organizer is rejected.
5. Add email attendees/additional guests, check the headcount, and continue to **Review & confirm**. For recurrence, review every actual occurrence and its availability.
6. Press **Confirm booking** once.
7. Check Approved state and correct organizer; queued confirmation goes to that organizer/attendees/staff.

A newly created staff booking is Approved without the employee Pending stage. It still needs check-in. New recurring staff bookings create Approved occurrences; existing Pending requests stay Pending after a room-policy toggle or unchanged save, but a substantive valid edit in an unchecked room can approve them automatically.

### Exception behavior

A nonempty reason (maximum 500 characters) bypasses normal horizon, weekend/holiday, office-hour, duration and increment checks. For example: **Board meeting approved by Front Desk outside normal office hours**. It records the reason and the staff booking/change action.

The following cannot be bypassed:

- End after start and future start time.
- Active room and active eligible organizer.
- Room capacity calculation.
- Conflicts with bookings, Pending holds, closures and buffers.
- Recurring creation limits of 15 occurrences and at most 366 days.

The configured post-meeting gap still applies. The calendar normally marks closed times as unavailable even for staff; an approved exception is entered through the booking form. Staff edit values, including original custom times and override reason, are prefilled; a substantive edit to Pending confirms it only if the selected room is unchecked; a checked-room request still needs explicit approval. Without JavaScript, the native form supports the same fields/validation, including staff organizer and override fields.

### WDN third-floor senior-management priority

Priority is manual, with no automatic ranking/displacement. Review impacted meetings and communicate with organizers under company practice. Reject a Pending request, cancel an eligible meeting, or reschedule it to free the interval; then create the priority meeting. Put the explanation in the decision/cancellation reason and use an override reason if the replacement itself requires a rule exception. An override cannot occupy a still-held interval.

## 6. Add, edit or deactivate rooms

1. Open **Staff desk → Rooms**. This list contains active and inactive records.
2. Select **Add room +**, or **Edit** in an existing row.
3. Enter name, location, floor, positive seat capacity, description and room instructions.
4. Enter facility names separated by commas, semicolons or newlines, such as **Projector, Whiteboard, Video conferencing**.
5. Optionally choose a real room **Photo**. Use a still JPEG, PNG or WebP no larger than 5 MiB and 12 million pixels; no photo is required.
6. Select **Active** to offer it for bookings; clear Active to retire it.
7. Set **Requires approval**: checked means employee requests require staff review; unchecked means valid employee requests are immediately Approved. New rooms default to checked.
8. Save and check **Room saved**, the updated row and room image in the booking wizard when appropriate.

Example: name **Room 1**, location **Kantipat**, floor **3**, capacity **8**, instructions **Leave the room tidy and switch off the projector**. Use actual office data; example rooms are not automatically imported into production.

Direct links: [staff room list](http://mbs.wdn.com.np/staff/rooms/) and [Add room](http://mbs.wdn.com.np/staff/rooms/new/). Room editing is on **Staff desk → Rooms → Edit**, not the employee Rooms page. It requires staff password/email-code sign-in.

### Change approval directly from the room list

1. Open **Staff desk → Rooms** in a verified staff session.
2. Find the correct room by name/location/floor and change its **Requires approval** checkbox.
3. With JavaScript, the row saves immediately when changed. Without JavaScript, press the **Save** button in that row.
4. Verify the saved checkbox and **Room approval setting saved** message. The audit log records the old/new setting when it changes.
5. Review existing Pending requests separately; use Approve/Reject, or make a substantive valid edit if appropriate.

| Setting | New employee booking / substantive employee edit | Staff-created booking |
| --- | --- | --- |
| Checked | Pending; hold retained until review/expiry | Approved immediately |
| Unchecked | Approved immediately; confirmation/check-in queued | Approved immediately |

Changing this field does not rewrite existing Pending or Approved records. A Pending request remains Pending after an unchecked toggle or unchanged form save. A substantive valid edit to it in an unchecked room can confirm it automatically, whether made by its organizer or verified staff. Recurring creations follow the selected room's policy for each occurrence; no existing series is bulk-converted. The setting takes effect on subsequent saving without an application restart. Migration 0011 checks it for existing rooms to preserve their current review requirement.

### Replace or remove a room photo

1. Open an existing room's **Edit** form.
2. To replace the photo, choose a new supported file. To remove it, select **Remove current photo** instead; do not select removal and upload together.
3. Save and verify the new preview, or its absence after removal. A browser cannot retain a selected upload after a failed form submission; reselect the file if correcting an error.
4. If the upload reports an unreadable, animated, oversized or unsupported file, choose a suitable still image. If saving reports a storage problem, ask IT to inspect the media volume; do not reset the database.

The application converts accepted files to JPEG up to 1920 pixels on the longest edge, strips supplied metadata and generates filenames. Replacing/removing deletes the previous file only after the room change commits. Employees can view active room photos while signed in; verified staff can preview inactive room photos too. There is no public media URL or photo gallery. IT must back up the photo volume together with room records, because a database dump alone cannot restore photos.

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

### Upload an Excel holiday schedule

1. Open **Staff desk → Holidays** and select **Download template**. The workbook has a **Holidays** sheet, with **Date** in A1 and **Occasion** in B1; enter your approved dates starting on row 2.
2. Save as **`.xlsx`**. Use Gregorian/AD Excel date cells or text in **YYYY-MM-DD** format. Enter one date and a required holiday name (up to 160 characters) per row. Enter a separate row for each day of a multi-day holiday. Do not use duplicate dates, merged cells or formulas.
3. Select **Upload Excel**, choose the file and press **Preview holidays**. Maximum upload size is **2 MiB** and the schedule may contain up to **1,000 holiday rows**. A header-only template is not a completed schedule.
4. Correct any errors shown with Excel row numbers and upload again. No dates are imported while the file contains an error. The preview shows **New holiday**, **Update name** (with the previous name), or **No change**, plus existing meeting counts for each date.
5. Review the warning if Pending, Approved or Checked in meetings overlap an uploaded holiday date in Nepal time. Open **Staff desk → Bookings** to inspect them. The import does not cancel, reschedule or notify those meetings. Select the acknowledgment that existing meetings remain saved and need staff review.
6. Press **Confirm import**. New dates are added and changed names are updated together; unchanged dates stay unchanged. Holidays missing from the file are kept. Importing requires the same currently verified staff session and the saved preview; no upload field values alone can confirm it.
7. Check the success counts and **Saved holidays**, then open **Calendar** at one imported date. Holiday names appear there and normal employee booking is closed across all rooms.

The preview expires after **15 minutes** and is consumed once. Upload again if it expired or was already confirmed. If holiday data or affected meetings change before confirmation, the application refreshes the preview and asks you to review and confirm again. **Cancel** returns to Holidays without importing. The batch is recorded as `holiday_imported`, and added/renamed entries have `holiday_saved` audit records. Uploaded workbook bytes are not retained as a room photo or permanent document.

Example rows below illustrate the format; they are not an approved office holiday schedule:

| Date | Occasion |
| --- | --- |
| 2026-12-25 | Christmas |
| 2027-01-01 | New Year |

### Add or remove a single date

1. Open **Holidays**, then **Add a single holiday**.
2. Enter a Gregorian date and occasion name, for example **Company holiday**.
3. Press **Add holiday**. An existing date updates that holiday's name rather than adding a duplicate.
4. Review scheduled bookings on that date separately if needed.
5. Use the saved entry's **Remove** action to delete that date; the removal is audited.

Dates must be valid and name is required (up to 160 characters). Holiday entries are unique by date. Daily normal recurrence skips these dates; weekly/monthly series containing a holiday are rejected unless staff enters an exception. Existing meetings are not automatically cancelled. Removing a holiday does not open weekends, which remain closed independently.

## 10. Manage departments

Front Desk and Administrators have identical access to this catalog.

1. Open **Staff desk → Departments**.
2. Select **Add department** and enter the required name (up to 120 characters).
3. Keep **Active** selected to offer the option in booking/profile dropdowns, then save.
4. To rename or retire an option, select **Edit** in its row, change the name or clear **Active**, and save.
5. Check the department list and relevant dropdown. Changes take effect without restarting the application and are recorded in the audit log.

Names must be unique regardless of capitalization; for example, **Sales** and **sales** cannot be separate entries. Initial options are **Accounts, Administrative, Logistics, Sales, Oracle Support, Dell Support, Toshiba and ATM support**. Upgrade migration `0012_department` also imports existing nonblank department labels so that legacy choices are retained.

Use deactivation instead of deletion. Renaming/deactivation does not rewrite department labels already saved on profiles or bookings. Reports continue to group meetings by their saved labels. Department is optional; a blank value appears as **Unspecified** in reports. This catalog does not grant staff privileges or impose a separate approval rule.

When editing a profile, a booking or an existing person in People, their previously saved label can remain as the current value even if it is inactive or renamed. New bookings/accounts select active options only. An inactive/renamed profile label is not prefilled into new booking requests; choose an active option or leave the optional field blank.

Direct links: [Department list](http://mbs.wdn.com.np/staff/departments/) and [Add department](http://mbs.wdn.com.np/staff/departments/new/).

## 11. Manage people and access

### Add/update an employee

1. Open **People**.
2. Enter an eligible company email and names, then choose an optional department from the dropdown.
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

Active approved-domain employee accounts also supply name/email suggestions in the booking Attendees field. First successful company-email sign-in registers a new employee; staff-created active accounts are also eligible. Inactive accounts disappear from suggestions. Directory participation is not staff access.

An access change invalidates existing login sessions and pending sign-in challenges. Password changes invalidate existing sessions as well. Records/bookings/audit history remain; account deactivation does not cancel bookings automatically. You cannot remove your own staff role or deactivate your own account through People. There is no separate administrator-only permission tier or grant approval chain.

## 12. Generate reports and export Excel

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

## 13. Use audit history

1. Open **Audit log**.
2. Select an action, for example `booking_approved`, `booking_modified`, `user_access_modified` or `room_modified`.
3. Optionally enter actor-email search.
4. Press **Filter** and inspect timestamp, actor, target type/ID and outcome.
5. Use Reset to clear filters; page through older events.

The UI is read-only and displays 50 events per page. “System” means no actor was attached to that automated/anonymous event. Audit supports investigation of booking decisions, access/password actions, room/rule/holiday changes and selected sign-in/mail failures. It does not log every page view, provide full email bodies or replace IT's service logs. There is no UI audit delete/export button or automatic one-year purge.

## 14. Email issues and escalation

Booking events are queued independently of saved reservation transactions. Login links, staff codes and setup messages are sent directly during the request, so their failure may appear in audit/logs rather than the Failed emails dashboard count.

For queued booking mail, the worker attempts at most five deliveries, with backoff. Some Failed messages are awaiting automatic retry; exhausted failures need authorized IT retry after repairing the cause. Obsolete messages are superseded when bookings change. Relay acceptance is not proof of final mailbox delivery.

Messages now provide branded HTML with a plain-text alternative. Organizer-approved mail includes a private Check in action; signed-in company attendees can read their meeting in My meetings but cannot use organizer check-in or manage it. External recipients and former participants with neither current participation nor active staff access are given Contact organizer. Intentional change notifications to former participants do not restore current meeting access. Email HTML/client display issues do not change saved booking status or extend the deadline.

If users report missing mail:

1. Confirm current booking state and correct organizer/attendee addresses.
2. Check dashboard Failed emails; do not conclude delivery succeeded from a zero count alone.
3. Ask IT to inspect SMTP, worker heartbeat and queue using [troubleshooting commands](troubleshooting.md).
4. If the meeting has started and attendance is verified, perform Manual check-in **before** its deadline when needed.
5. Do not promise the system will extend the deadline during an email outage.

Record ordinary page/action, approximate Nepal time, booking ID and visible error/request reference if present. Keep passwords, email codes, token-bearing links and `.env` contents private. Direct HCL/Outlook calendar sync is deferred; missing entries in those calendars are not evidence of failed MBS confirmation delivery.

## 15. Handover and retention

Front Desk owns review, guest/preparation requests, manual priority arrangements, room records and appropriate access changes. IT owns server/worker/mail health, database credentials, backups/restores, Docker updates, logs/disk monitoring and technical incident diagnosis. Staff should escalate service errors rather than change database rows to bypass workflows.

Keep booking/audit history under the approved company retention policy, including any requirement to retain at least one year. The application currently has no automatic retention purge. Room inactivity, account inactivity and cancelled reservations retain their history. See [deployment](deployment-http.md) and [troubleshooting](troubleshooting.md) for maintenance, diagnostics and recovery commands.
