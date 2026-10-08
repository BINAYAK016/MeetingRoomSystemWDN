# Features and use cases

**Meeting Booking System (MBS)**
**Transgate Tech | Binayak Bhandari**
Documentation checked against application source on **8 October 2026**.

This reference describes implemented behavior. The selected office deployment is **http://mbs.wdn.com.np**, bound to **192.168.50.222:80**, with PostgreSQL and Docker Compose. Both `@wdn.com.np` and `@transgate.com.np` are accepted employee domains in the production profile. Staff means Front Desk or Administrator: both have the same permissions.

Use the [employee guide](user-guide.md) for employee workflows, the [staff guide](staff-guide.md) for administration, the [HTTP deployment guide](deployment-http.md) for installation, and [troubleshooting](troubleshooting.md) for diagnostic commands. This is a feature reference, including behavior that is easy to miss in normal use.

## Contents

1. [Branded web interface](#branded-web-interface)
2. [Accounts, sessions and permissions](#accounts-sessions-and-permissions)
3. [Page and feature directory](#page-and-feature-directory)
4. [Room discovery and availability](#room-discovery-and-availability)
5. [Booking fields and validation](#booking-fields-and-validation)
6. [Approval and booking lifecycle](#approval-and-booking-lifecycle)
7. [Recurring meetings](#recurring-meetings)
8. [Check-in and automatic release](#check-in-and-automatic-release)
9. [Email notifications](#email-notifications)
10. [Staff administration](#staff-administration)
11. [Reports and audit](#reports-and-audit)
12. [Use-case catalogue](#use-case-catalogue)
13. [Implemented scope and limitations](#implemented-scope-and-limitations)

## Branded web interface

The application includes the Transgate logo, navy/red brand colors and the requested Times New Roman font (with Times/serif fallbacks). It provides responsive form/cards/table layouts, keyboard focus styling, a Skip to content link, named table regions, accessible status/error messages and confirmation dialogs for consequential form actions. Core pages/forms work without JavaScript; JavaScript adds the three-step booking wizard, room availability previews, confirmations and repeated-click prevention during a submitted request. Wide calendar/report tables scroll horizontally on smaller screens. No external font installation, browser plug-in or webcam/location access is required.

## Accounts, sessions and permissions

### Employee access

An eligible employee enters a company email at [Employee sign-in](http://mbs.wdn.com.np/sign-in/). Email addresses are trimmed and normalized to lowercase. Eligibility checks the complete domain after `@`; a different domain or a subdomain is not automatically accepted.

The employee receives a one-time link valid for **15 minutes**, opens it and presses **Continue to workspace**. Opening the link alone does not authenticate the user or consume it; the confirmation button performs that action. This accommodates mailbox scanners that open links. The account is created on successful confirmation if it does not exist. There is no employee password requirement or independent employee sign-in code entry screen.

The request page uses a generic response. “Check your email” is not proof that the account is eligible or that the relay delivered the message. Invalid domains, inactive accounts, throttling and delivery failures can prevent a usable link. Request limits are **three requests per address** and **20 per source IP** in a 15-minute window.

### Staff access

Staff sign in at [Staff sign-in](http://mbs.wdn.com.np/staff/sign-in/) using their company email and password. The second factor is an **eight-digit email code**, valid for **10 minutes**. A challenge permits at most **five failed attempts**. Starting another successful password challenge invalidates older staff codes for that account.

A staff account first receives a password setup link from an existing verified staff member or the server's `create_staff_account` command. The setup/reset link lasts **one hour**. Passwords must match, contain at least **12 characters**, and pass the application's password validators (including common, numeric-only and account-similarity checks). There is no public “forgot password” self-service form; staff request another setup link from a colleague or IT.

The password stage limits requests to **five per address** and **30 per source IP** in a 15-minute window. The employee link route can sign a staff member in as an employee, but does not grant verified staff powers. A staff member who uses employee link sign-in must complete staff password-plus-code sign-in before using management pages.

### Session lifecycle

Successful employee or staff sign-in creates an **eight-hour** session. This is an expiry from sign-in, not a documented sliding idle timer. Sign out removes the current browser session. Cookies must be enabled for sign-in confirmation, form submission and email check-in.

Staff permissions are checked against the active account and the session's verified staff status. Active/staff access changes in People revoke existing authentication sessions and pending sign-in challenges. Password changes also invalidate existing sessions. The account history remains. Account deactivation does not itself cancel its meetings; staff review those separately.

### Permission matrix

| Action or information | Employee session | Verified Front Desk / Administrator |
| --- | --- | --- |
| Browse active rooms, facilities and instructions | Yes | Yes |
| Day and week availability | Yes | Yes |
| Month availability | No; a month request falls back to week | Yes |
| See another organizer's private booking detail | No | Yes |
| See occupancy of another employee's slot | Yes, as unavailable | Yes, with a link to detail |
| Read own meeting title, attendees, notes and decisions | Yes | Yes |
| Submit own booking request | Pending if selected room requires approval; otherwise Approved | Yes, staff creation starts Approved |
| Book on behalf of another employee | No | Yes |
| Edit/cancel another organizer's eligible booking | No | Yes |
| Approve/reject requests | No | Yes |
| Enter a booking-policy exception | No | Yes, with an override reason |
| Manual check-in within the check-in window | No | Yes |
| Manage rooms, closures, rules, holidays and access | No | Yes |
| View reports, Excel exports and audit log | No | Yes |
| Use local test inbox on the office production server | No | No |

An attendee's invitation does not grant access to the organizer's detail page or editing rights. Staff and organizer can read Front Desk notes; those notes are not a separate staff-private comment field.

## Page and feature directory

Paths below are relative to `http://mbs.wdn.com.np`. Numeric identifiers in `{braces}` are assigned by the application; use page links rather than guessing IDs.

| Page / path | Purpose | Access |
| --- | --- | --- |
| `/` | Public landing page, or authenticated workspace overview | Public / signed-in employee |
| `/sign-in/` | Request employee email link | Public |
| `/sign-in/confirm/` | Confirm an email link opened in this browser | Pending email-link session |
| `/profile/` | Update own first name, last name and department | Signed in |
| `/rooms/` | Search/filter active room directory | Signed in |
| `/rooms/{room_id}/` | Facilities, description and instructions | Signed in; active rooms |
| `/calendar/` | Day/week availability; staff month view | Signed in |
| `/bookings/new/` | Three-step meeting request or approved staff booking | Signed in |
| `/bookings/availability/` | Read-only room availability for the full selected schedule/series | Signed in |
| `/rooms/{room_id}/photo/` | Authenticated optional room photo | Signed in; active room, or verified staff for inactive room |
| `/bookings/mine/` | Own Upcoming and History lists | Signed in |
| `/bookings/{booking_id}/` | Private detail, decision and available management actions | Organizer or verified staff |
| `/bookings/{booking_id}/edit/` | Edit one future pending/approved occurrence | Organizer or verified staff |
| `/check-in/confirm/` | Confirm arrival after opening emailed check-in link | Valid organizer link and browser session |
| `/staff/sign-in/` | Staff password stage | Public |
| `/staff/code/` | Complete pending staff email-code challenge | Pending staff challenge in same browser |
| `/staff/` | Staff overview and operational indicators | Verified staff |
| `/staff/bookings/pending/` | Pending queue, earliest start first | Verified staff |
| `/staff/bookings/` | Search/filter all booking statuses | Verified staff |
| `/staff/rooms/` | Active and inactive room administration | Verified staff |
| `/staff/rooms/new/` | Add a room | Verified staff |
| `/staff/rooms/{room_id}/` | Edit a room | Verified staff |
| `/staff/blocks/` | List room closures and remove them | Verified staff |
| `/staff/blocks/new/` | Reserve an unavailable period | Verified staff |
| `/staff/policy/` | Configure booking rules | Verified staff |
| `/staff/holidays/` | Add/update/delete company holidays | Verified staff |
| `/staff/users/` | Employee directory, profile fields and access controls | Verified staff |
| `/staff/reports/` | Date-range usage reports | Verified staff |
| `/staff/reports.xlsx` | Download selected report as Excel | Verified staff |
| `/staff/audit/` | Read-only, filterable action history | Verified staff |
| `/healthz/` | Application/database readiness | Health tooling; no booking information |
| `/livez/` | Process liveness | Health tooling; no booking information |

Email sign-in, check-in and password setup also have generated token-bearing routes. These are private links, not permanent navigation URLs. Do not copy them into logs or documentation. The custom staff pages are the administration interface; **no `/admin/` route is exposed**.

### Action and generated-link routes

These routes complement the page directory. Buttons/forms supply the required session-backed CSRF token; do not invoke management POSTs as unauthenticated GET links.

| Route | Method | Purpose / access |
| --- | --- | --- |
| `/sign-out/` | POST | End current login session |
| `/bookings/{booking_id}/cancel/` | POST | Organizer/verified staff cancels eligible record |
| `/staff/bookings/{booking_id}/approve/` | POST | Verified staff approves future Pending |
| `/staff/bookings/{booking_id}/reject/` | POST | Verified staff rejects Pending with reason |
| `/staff/bookings/{booking_id}/check-in/` | POST | Verified staff manual check-in during window |
| `/staff/rooms/{room_id}/approval/` | POST | Verified staff changes Requires approval; existing statuses retained |
| `/staff/blocks/{block_id}/cancel/` | POST | Verified staff removes active closure |
| `/staff/holidays/{holiday_id}/delete/` | POST | Verified staff deletes holiday entry |
| `/staff/users/save/` | POST | Verified staff saves profile/access state |
| `/staff/users/{user_id}/setup/` | POST | Verified staff sends active staff setup/reset mail |
| `/sign-in/link/{private_token}/` | GET | Stage email token and redirect to confirmation; does not consume it |
| `/check-in/link/{private_token}/` | GET | Stage check-in token and redirect to confirmation; does not consume it |
| `/staff/set-password/{private_uid}/{private_token}/` | GET / POST | Validate private setup link; POST sets password |
| `/dev/mail/` | GET | Loopback file-mail development only; production returns 404 |

## Room discovery and availability

### Workspace overview

After sign-in, the overview shows active room count, upcoming approved meetings, pending request count, booking-window length and office hours. It previews up to six active rooms and links to the full directory, calendar and booking form. The staff overview is a separate page with company-wide operational counts.

### Room directory and detail

The employee room directory supports:

- Search by room name, floor or description.
- Minimum seat count.
- Exact location and facility filters selected from active room values.
- Resetting filters and pagination, with **12 rooms per page**.
- Room cards with name, location, floor, capacity, facilities and **Staff approval required** or **Automatic approval**; staff can supply an optional real photo used by the booking wizard.
- Detail pages with descriptions, instructions, equipment labels and **Book this room**.

Facilities are descriptive free-text labels such as “Projector” or “Whiteboard”. They are not separate reservable inventory items. Minimum seats filters room capacity; it does not reserve seats or check attendee schedules. Only active rooms appear in employee search, detail and calendar views.

### Calendar

All booking times are **Nepal time (Asia/Kathmandu, NPT)**. The day view displays one column per active room and one row per configured booking increment. A free cell offers **Available +**, which preselects room/date/start time on the booking form. The wizard keeps those selections, proposes a duration/end time under the current policy, and lets the organizer adjust them and complete the remaining fields.

Calendar markings distinguish an available start, unavailable occupancy, the current user's own booking, and dates/times outside normal rules. Pending holds, approved bookings, checked-in/completed occupied intervals, room closures and meeting buffers can all make a cell unavailable. Other employees see generic occupancy. Organizers and verified staff can open booking detail links for accessible meetings.

Week view shows counts by day and room, with links to day view. Staff also get a month view. Counts cover active reservation records, including closures; they are not a count of approved meetings only. Day view marks closed weekends, holidays, past times, dates outside the horizon, insufficient time before closing, and insufficient time for a minimum meeting plus buffer before another reservation.

The calendar reflects the database when loaded. It is not a live push-updated feed or a guarantee that another person cannot reserve a slot. Availability is checked again when a form is saved. Reload after other users' changes. Dates more than 366 days from today fall back to today.

## Booking fields and validation

### Three-step booking flow

The booking page has workspace navigation and three steps:

| Step | Actions | Before continuing |
| --- | --- | --- |
| Schedule & details | Choose date, duration/start or custom times; select a room; enter title, meeting type, department, purpose, guest company, refreshments and special requirements; choose recurrence when creating | Check required meeting details and current room/time availability |
| Attendees | Add email addresses and additional guests without individual email entries; verified staff can set organizer for an employee | Check the displayed total against room capacity; organizer is already counted |
| Review & confirm | Review room, date/time, actual recurring occurrences, meeting information and attendees; use Edit/Back to correct values | Submit once; only successful saving holds the interval |

Duration/time choices follow the current policy rather than a fixed quarter-hour rule. New booking defaults aim for a one-hour meeting within minimum/maximum duration and office hours, with an aligned future start on a working day. Room/date/start links from the calendar take precedence as selections; final validation still applies. An edit preserves its existing values and changes one occurrence only.

The room preview checks the **whole selected schedule**, including every eligible recurring occurrence, against Pending requests, approved/checked-in/completed occupied intervals, closures and required turnaround gaps. A room is available only if all the proposed occurrences fit. The review shows the actual occurrence list, including daily skips. Schedule changes refresh the preview. Preview is read-only: it neither holds a room nor sends invitations. The server repeats authoritative checks on final submission, so another user's intervening reservation can still produce an error.

Availability reveals room metadata and occupied time ranges; it does not disclose another organizer's email, title, description, notes, booking state or closure reason. During an authorized edit it excludes the occurrence being edited, but keeps other occurrences in the same series. Attendee capacity is checked separately and again on save.

If JavaScript is unavailable, the underlying native form displays room/date/start/end and meeting/attendee fields with the same Submit action. It retains server validation and the same request/approval behavior; live preview and staged review require JavaScript. A failed request displays field/general errors and retains entered values so they can be corrected.

### Fields

| Field | Meaning / rule |
| --- | --- |
| Room | An active room, required |
| Date, start time, end time | Same-day future meeting in Nepal time; end after start |
| Title | Required, at most 200 characters |
| Description | Optional, at most 10,000 characters |
| Meeting type | Internal, External, or Internal + External (`mixed`) |
| Guest company name | Required for External and Internal + External; at most 200 characters |
| Additional guests without email addresses | Stored as external attendee count; numeric value from 0 to 500; do not double-count email-listed people |
| Department | Optional, at most 120 characters; initially copied from profile |
| Attendees | Up to 50 distinct valid email addresses; newline, comma, semicolon or whitespace separated |
| Refreshments requested | A request flag visible to Front Desk, not a fulfilment or stock workflow |
| Front Desk notes | Optional preparation information, at most 10,000 characters; visible to organizer and staff |
| Recurrence | One meeting, Daily, Weekly or Monthly |
| Until date | Required for recurring creation; cannot precede first date |
| Organizer email | Verified staff only; blank means current staff user; otherwise eligible active employee |
| Override reason | Verified staff only, at most 500 characters; a nonempty reason enables policy exceptions |

Attendee addresses are normalized to lowercase and deduplicated. Attendees may use external domains; the company-domain restriction applies to account sign-in and organizer selection. The application does not check attendees' personal calendars. External attendee count represents additional people without individual listed addresses: avoid counting a person both in the email list and in the external count.

**Capacity calculation:** one organizer + distinct listed addresses other than the organizer + external attendee count. An organizer, five other listed emails and two unlisted external guests require eight seats. Staff exceptions cannot bypass capacity.

### Default booking rules

These are the source/migration defaults. Staff can change numeric/time values under **Rules**; the running database is authoritative.

| Rule | Initial value | Behavior |
| --- | --- | --- |
| Working days | Monday–Friday | Weekends excluded by application logic; no working-weekday editor |
| Opening / closing | 09:00 / 17:00 | Meeting start/end must fit inside these hours |
| Minimum duration | 30 minutes | Shorter normal bookings rejected |
| Maximum duration | 120 minutes | Longer normal bookings rejected |
| Time increment | 15 minutes | Start/end align to minute offsets from midnight, such as 10:00 or 10:15 |
| Gap after meeting | 15 minutes | Room remains occupied after meeting end |
| Advance window | 14 days | Every occurrence, and recurring until date, must stay inside calendar-date limit |
| Check-in deadline | 15 minutes after scheduled start | Confirmation must occur strictly before deadline |
| Holidays | Dates entered by staff | Normal bookings on listed holidays rejected |

The horizon uses Nepal calendar dates rather than an exact rolling 336-hour duration. If today is 7 October and the rule is 14 days, 21 October is the last eligible booking date. Past start times are always rejected, including a start earlier today.

A 10:00–11:00 meeting with the default gap occupies **10:00–11:15**. The next meeting can begin at 11:15 if its full occupied interval is available. The gap is appended after the end; it is not added both before and after. A meeting ending at office closing can have its buffer continue after closing.

### Concurrency and conflicts

Pending requests already hold room time. The application validates overlaps and PostgreSQL also rejects overlapping active occupied intervals, including simultaneous requests. Room locks and the database constraint cover bookings and closures. A stale calendar cannot create two reservations for the same occupied time. Choose another room/time if an error says unavailable. A conflict notice is also queued to the user who made the failed create/edit attempt.

Attendee count, future time, active room/organizer and room conflict rules still apply to staff. An exception reason bypasses normal advance-window, weekend/holiday, office-hour, duration and increment checks; it does not bypass those fundamental constraints. The configured gap still applies.

## Approval and booking lifecycle

### State reference

| Status | How reached | Holds occupied interval? | Normal available next actions |
| --- | --- | --- | --- |
| Pending approval (`pending`) | Employee creation/substantive edit in a room requiring approval; existing Pending retained after room-policy toggle or unchanged save | Yes | Future edit; staff approve/reject; cancel; automatic expiry at start |
| Approved (`approved`) | Staff approves Pending; staff creates; employee creates/substantively edits in an unchecked room; substantive staff edit of Pending in an unchecked room | Yes | Future edit; cancel; organizer or manual staff check-in during window; automatic No show if missed |
| Rejected (`rejected`) | Staff rejects Pending with reason | No | Read history/reason; submit a separate new request |
| Checked in (`checked_in`) | Valid email check-in or staff manual check-in | Yes | Cancel if necessary; automatic completion after end |
| Completed (`completed`) | Worker reconciles a checked-in meeting after scheduled end | Yes, its historical occupied interval | View/report; no normal edit/cancel |
| Cancelled (`cancelled`) | Organizer/staff cancellation or approval-window expiry | No | View history; create a new request |
| No show (`no_show`) | Approved meeting misses check-in deadline | No | View history; create new booking if required |
| Blocked (`blocked`) | Staff room closure | Yes | Remove closure |
| Closure cancelled (`block_cancelled`) | Staff removes closure | No | View closure history |

Completed meetings keep their historical interval to preserve conflict integrity. This does not block future dates. No show is the release state for a missed check-in; it is distinct from `cancelled` even though it releases the room.

### Submission and review

The selected room's **Requires approval** setting determines employee submission status. It defaults to checked: submission creates Pending, queues a request message to the organizer and active staff, and does not issue approved invitations to attendees. The detail page shows that review is required. Staff review each future Pending request and approve it or reject it with an explanation of up to 500 characters.

For an unchecked room, a valid employee submission starts Approved immediately and queues normal confirmation to organizer/attendees/staff, including eligible organizer check-in instructions. No staff reviewer is invented: automatic approval records a timestamp with no approval actor. The current room setting is read under a transaction lock when saving; a preview does not override it. Capacity, conflicts, buffers, date/duration rules and ownership checks are identical for both policies.

Approval records the staff actor and time, changes state to Approved and queues confirmation. The room and organizer must still be active; the meeting must not have started. Approval confirms the stored request; it does not re-run every changed holiday/policy/capacity value. If room details or rules changed after submission, staff should review the request manually.

Rejection records staff actor, time and reason, releases the interval and queues a rejection message to the organizer and active staff. The organizer can read the reason. A rejected occurrence is not editable or approvable again; submit a new request if arrangements change.

### Modification

A substantive change includes room, organizer, time/occupied buffer, meeting fields (for example title, department, purpose or refreshments), or the normalized attendee set. A new configured gap can change the saved occupied interval even when the visible meeting times stay the same.

Only future Pending or Approved bookings may be edited. Ordinary employees edit their own bookings. Verified staff can edit any eligible booking, including changing organizer. Editing a recurring occurrence changes that occurrence only; recurrence fields are not offered on the edit form.

A substantive employee edit follows the **selected room's current policy**, even when moving to another room. Checked means Pending with approval metadata cleared and an updated request queued; unchecked means Approved with an automatic approval timestamp and no attributed reviewer. Old check-in links and obsolete queued mail are invalidated.

A form saved without substantive changes keeps its original status, including a Pending request whose room was later unchecked. Staff editing Approved keeps it Approved and queues changes. A substantive staff edit to Pending in a checked room leaves it Pending for a separate Approve action; in an unchecked room it becomes Approved automatically. A Pending-to-Approved edit queues confirmation; an Approved-to-Approved edit queues change notices. Changing the room setting alone does not rewrite any booking or queue approval mail.

Availability, capacity and applicable policy are checked for the proposed new state. Failed edits do not discard the existing booking. Revision numbers prevent outdated pending email from being sent as if it described the current booking. Change messages for approved bookings include previous attendees/organizer when those recipients were removed or changed.

### Cancellation and expiry

Organizers and verified staff may cancel Pending, Approved or Checked in bookings. The reason is stored (up to 240 characters), the interval is released, old check-in tokens are invalidated and cancellation messages are queued. Cancellation is an explicit confirmed action, not a delete.

Pending requests still pending at their scheduled start are cancelled with **“Approval window expired before the meeting started”**. The worker performs reconciliation, and booking creation/edit also releases overdue pending/no-show holds before checking availability. This is not a waitlist or automatic approval process.

## Recurring meetings

Recurring creation supports **Daily**, **Weekly** and **Monthly**, using a first date and inclusive until date. Each saved occurrence has its own status, approval, check-in, emails and management actions, associated with a series record.

| Pattern | Actual behavior |
| --- | --- |
| Daily, normal rules | Creates each company working day between first/until dates; skips weekends and configured holidays |
| Weekly | Every seven days from first date; a closed occurrence makes the whole normal request invalid |
| Monthly | Same day number in later months; clamps to the last day of a shorter month |
| Staff exception | Can include normally excluded dates, within remaining recurrence safety limits |

All occurrences must validate and be available. **The series saves all-or-nothing**: one conflict rejects the entire creation; no partial series is kept. Creation is limited to **15 occurrences** and a date span of at most **366 days**, even with an override.

For normal users the **until date itself** must be inside the configured advance window. The system rejects a distant until date; it does not silently truncate a year-long series to two weeks. Under the default 14-day window, a monthly request usually creates only its first occurrence. The organizer books later months manually when they enter the window. A month-end first date can, depending on the current date/window, produce a second short-month occurrence.

There is no automatic rolling creation, “cancel whole series”, series-wide edit, series-wide approval or background extension into later months. Manage and review occurrences individually.

## Check-in and automatic release

The organizer's approved confirmation/change emails and reminder may include a **one-time check-in link**. Attendees and staff receive event notifications, but only the organizer recipient gets that link. The link opens a confirmation page; arrival is recorded only when **Check in now** is pressed.

Check-in is allowed from scheduled start **inclusive** until the configured deadline **exclusive**. A 10:00 meeting with a 15-minute rule can be checked in at 10:00 through just before 10:15; at 10:15 it is too late. Early confirmation is rejected and can be retried from the same staged page after start.

The check-in link proves possession of the organizer's emailed token. The current implementation **does not require a prior employee login session**. The browser still needs its session cookie and CSRF-protected confirmation form. Organizer/account/token/reservation are checked, and expired, used, cancelled, modified or mismatched tokens are rejected. Treat the link as private.

Verified staff can use **Manual check-in** on an Approved booking detail page during the identical window. The button can be visible earlier, but the server rejects an out-of-window action. Manual check-in invalidates outstanding email check-in tokens and records the staff actor.

After the deadline an unchecked Approved meeting becomes **No show**, releases the whole occupied interval and queues release notifications. A late click cannot revive it. Checked-in meetings become Completed when their scheduled end passes. The worker normally reconciles about every **30 seconds**, so state changes occur on the next successful cycle, not necessarily at the exact boundary. Worker and SMTP health matter; delivery failures do not extend the check-in deadline.

## Email notifications

### Who receives what

Recipients are deduplicated by address. “Staff” below means every currently active staff account when that event/reminder is queued.

| Event | Organizer | Listed attendees | Active staff | Check-in link |
| --- | --- | --- | --- | --- |
| Employee request / updated Pending request | Yes | No | Yes | No |
| Rejection | Yes, with reason | No | Yes | No |
| Approval / automatic approval / staff creation confirmation | Yes | Yes | Yes | Organizer recipient only while valid |
| Approved booking change | Yes | Yes, including former removed recipients | Yes | Organizer recipient only while valid |
| Cancellation | Yes, with reason | Yes | Yes | No |
| No show release | Yes | Yes | Yes | No |
| Successful check-in | Yes | Yes | Yes | No |
| Reminder | Yes | Yes | Yes | Organizer recipient only while valid |
| Conflict on failed create/edit | User who attempted action | No | No extra staff broadcast | No |

Login links, staff codes and password setup emails are sent directly during their requests. Booking events use a separate database queue, so a saved meeting is not rolled back because subsequent SMTP delivery fails.

### Timing and retry behavior

Approved future meetings become eligible for a reminder within **one hour** of start. The worker queues it once per recipient, booking revision and scheduled start. This is not an exact timer guaranteeing delivery at T−60 minutes. A booking approved inside that hour becomes eligible on the next reconciliation. Pending/rejected/cancelled meetings do not get an approved reminder.

The worker normally reconciles states/reminders every 30 seconds and attempts one queued email per iteration. Backlog and SMTP latency can delay delivery. Failed queued mail retries up to **five total attempts**, with automatic retry delays of 2, 4, 8 and 16 minutes after failures one through four. After the fifth failure it remains Failed until IT requeues an eligible job; its recorded next-attempt timestamp is 32 minutes ahead but does not trigger an automatic sixth send. Recovery uses leases to avoid concurrent claims; a crash after SMTP acceptance can still cause duplicate mail when its lease is recovered. Mail delivery is not exactly-once.

Obsolete events are marked **Superseded** when state/revision changes. Worker checks current booking state before delivering related queued mail. Disabled/unconfigured SMTP leaves notifications waiting; it does not verify mailbox delivery. An SMTP “accepted” response proves relay acceptance, not final inbox placement. See [troubleshooting](troubleshooting.md) for queue inspection, worker checks and retry commands.

## Staff administration

### Dashboard and bookings

Staff Overview displays all Pending requests, today's approved/checked-in/completed meeting count, active rooms, today's No shows, failed mail and up to 12 upcoming Approved meetings. The failed-mail number is a signal to investigate with IT; the dashboard is not a notification body/token viewer.

Bookings filters by title/room/organizer search, status, room and inclusive start-date bounds. General Bookings is latest meeting first; Pending queue is earliest scheduled start first. Lists paginate (normally 25 items) while preserving filters. Staff can open details, review, edit/cancel and book on behalf.

### Rooms

Staff add/edit room name, location, floor, positive capacity, description, instructions, facilities, optional real room photo, Active state and **Requires approval**. The combination of name/location/floor must be unique. Facilities accept comma, semicolon or newline separators, up to 50 names of at most 120 characters, deduplicated case-insensitively.

Photo upload accepts a still JPEG, PNG or WebP up to 5 MiB and 12 million pixels. The server generates a JPEG no larger than 1920 pixels on its longest edge, removes supplied metadata and gives it a generated filename. Existing rooms without photos remain valid. Edit can replace a photo or select Remove current photo; selecting both is rejected. Replacement/removal deletes the previous file only after the database change commits. Photo delivery requires authentication; ordinary employees cannot fetch inactive room photos, while verified staff can preview them. No public media directory is served.

Deactivation removes the room from employee discovery/new selection and prevents approval while inactive. It preserves bookings/history; it does not automatically cancel meetings or prevent a previously approved meeting reaching its check-in flow. Reconcile affected meetings before deactivating. There is no hard-delete room action. Edit the same record or deactivate it when its history should remain associated.

### Room approval policy

**Staff desk → Rooms** contains a **Requires approval** checkbox for each active/inactive room. With JavaScript, changing it submits that row immediately; without JavaScript, select the desired state and press that row's **Save** button. The add/edit form provides the same field. Checked is the default for a new room and for every existing room upgraded through migration 0011.

Checked rooms require staff review of employee creations/substantive edits; unchecked rooms confirm those valid requests immediately. Staff-created bookings remain Approved for either setting. A saved toggle takes effect for later writes without a process restart, and is audited as `room_approval_changed` with its old/new values. The staff-only POST validates CSRF/current verified access and locks the room. It changes no booking status: an existing Pending request still needs explicit review or a substantive eligible edit; an existing Approved meeting is not demoted. Use the Pending queue to resolve the backlog deliberately.

### Closures

Staff may reserve a future same-day start/end period with a reason (up to 240 characters). Closures use the room-conflict constraint and cannot displace a Pending or Approved hold. They block exactly the chosen interval without appending the meeting gap.

Closures do not apply normal meeting horizon, working-day, office-hour, minimum/maximum-duration or server slot-alignment checks, although the time widget uses the configured step. They are intended for maintenance and other unavailable periods. The UI supports one date per closure; split a multi-day closure into separate entries. Removing one releases it and keeps a “Closure cancelled” history entry. There is no dedicated closure edit form; remove and recreate if necessary.

### Rules and holidays

Timing rules are one office-wide policy, not different limits per room/user. Editable fields are opening/closing times, minimum/maximum meeting minutes, slot increment, post-meeting gap, advance days and check-in minutes. The separate Requires approval checkbox is managed per room, not in Rules.

The form enforces ordered office hours, ordered duration limits, duration limits as whole increments, office hours aligned to increments, minimum duration fitting within office hours, and check-in closing within the shortest permitted meeting. Numeric bounds are minimum/maximum duration 1–1440, increment 1–60, gap 0–120, advance 1–366 and check-in 1–1440, subject to those cross-field checks.

Changes apply to subsequent validation. Existing occupied buffers are stored with each booking and are not rebuilt when the gap changes. Check-in uses current policy at confirmation/reconciliation, so changing its deadline affects existing Approved meetings. Adding a holiday or changing hours does not cancel saved bookings. Review affected requests/meetings.

Holidays use a unique date and a name (up to 160 characters). Saving an existing date updates its name. Remove deletes that entry and records an audit event. Weekends remain closed independently of holidays.

### People and access

People searches email/name/department and filters Everyone, Staff or Inactive. Staff create/update names, department, Active state and Front Desk / Administrator flag. Email identifies the account: changing the email field creates or updates the account at that address; it is **not** an email-rename feature.

Granting staff does not automatically send setup mail. Save the active staff account, then use **Email setup link** in the row. The same button resets a password. Inactive/nonstaff rows cannot request staff setup.

Removing staff keeps employee access when Active remains selected; deactivation prevents normal sign-in. Access changes revoke current authentication and pending challenges. Existing bookings remain for separate review. You cannot deactivate/remove your own staff access on this page. There is no user hard-delete action or approval chain for staff grants: all verified staff have these powers.

### Manual senior-management priority

There is no automatic rank/priority engine. Front Desk handles WDN third-floor senior-management priority manually: review plans, reject/cancel or reschedule the displaced booking with a reason, then make the replacement. An override cannot overlap the still-held interval. Communicate through the company's normal process; MBS records the reservation decision/reason and queues event emails.

## Reports and audit

### Reports

Report ranges are inclusive Nepal start dates. Presets are Today, This week, This month, This quarter and This year, with period-to-date end points. Default is this month's first day through today. Custom ranges accept an end minus start span of at most 366 days; reversed/excessive ranges show an error and fall back on the report page. Excel rejects an invalid range.

Booking counts include **all booking statuses**, including Pending, Rejected, Cancelled and No show. Closures are not bookings. Department and organizer totals count those records; blank department becomes “Unspecified”. Room rows include configured inactive rooms and are sorted most booked first.

Utilization is an **estimate of checked-in/completed scheduled meeting time** divided by bookable time in the full selected period. It uses current Monday–Friday office hours, excludes current holidays and active closures, and clips verified meeting intervals to those windows. It excludes meeting buffers, Pending/Approved-only time and No shows. A checked-in meeting contributes its scheduled full interval, not a sensor measurement of actual attendance or early departure. Overlapping intervals are merged to prevent duplicate minute counting. Meetings beginning before the range can contribute clipped usage minutes without counting as a start-date booking in that range.

Historical policy, room activation, holiday changes and cancelled-closure availability are not reconstructed. A policy edit can change historical utilization. A future-inclusive range increases available time before it has been used; choose an appropriate period when interpreting percentages.

**Excel export** contains Bookings, Room usage, Departments and Organizers worksheets. Booking fields are ID, date, start/end, room, organizer, department, raw status and title. Headers, column sizing, filters and frozen first rows are included; user text is emitted as literal strings instead of executable spreadsheet formulas. It is not a database backup or a full meeting-notes export.

### Audit log

The read-only staff Audit log records timestamp, actor (or System), action, target type/ID and outcome. Filter by exact action and actor-email substring; pagination uses 50 events per page. It covers sign-in/access/password setup outcomes, room/policy/holiday administration, booking creation/changes/decisions/cancellation/check-in/expiry and relevant mail/security events. System/anonymous events can have no actor. It is not a copy of every page view or every email message.

Structured details may exist in the database for authorized IT diagnosis, but the UI displays summary columns. There is no edit/delete/export button for audit records. The application does not automatically purge records after one year; backup/retention policy and any future cleanup are operational responsibilities.

## Use-case catalogue

Examples assume an illustrative eight-seat room and default policy. Adjust dates so they are future working dates within the current window; sample email addresses are placeholders, not actual recipients. Step-by-step versions are in the employee/staff guides.

| ID | Scenario | Actor and preconditions | Workflow / result |
| --- | --- | --- | --- |
| UC-01 | First employee visit | Eligible active mailbox | Request link → open within 15 minutes → confirm → account/workspace; no password |
| UC-02 | Invalid/expired employee link | Employee | Request new link; generic request screen does not confirm eligibility/delivery |
| UC-03 | Staff first login | Access granted, setup email received | Set valid 12+ character password → staff password sign-in → newest eight-digit code → staff desk |
| UC-04 | Staff uses employee login | Staff email, employee session | Employee functions available; management redirects to staff sign-in until MFA completed |
| UC-05 | Find projector room for six | Signed-in employee | Rooms → seats 6 → Projector → instructions → calendar; no match means change filters/contact staff |
| UC-06 | Reserve reviewed team meeting | Employee, free room with Requires approval checked | Future working Thursday, 10:00–11:00, Internal, “Team planning”, colleagues listed → Pending hold → review |
| UC-07 | External or mixed client visit | Employee, adequate seats | External or Internal + External, “Example Partners”, three unlisted guests + two listed colleagues → six seats; missing company rejected |
| UC-08 | Concurrent same-time requests | Concurrent signed-in users | One transaction holds interval; other create fails without duplicate; choose another time/room |
| UC-09 | Approve request | Future Pending, active room/organizer | Pending queue → detail → Approve → Approved, actor/time and confirmation mail |
| UC-10 | Reject request | Pending | Reason “Use larger room for visitor count” → Reject → Rejected, slot free, reason visible |
| UC-11 | Edit Approved meeting | Organizer, future Approved | Change end 11:00 to 11:30 → validate → Pending if selected room is checked, otherwise Approved; old check-in link invalid |
| UC-12 | Staff edits Approved | Verified staff, future Approved | Change eligible fields → Approved retained → change mail includes removed recipients |
| UC-13 | Daily stand-up | Employee, all slots free | Daily 09:00–09:30 for future week → skip closed dates → all Pending in checked room or Approved in unchecked room; any conflict rolls back the whole series |
| UC-14 | Weekly holiday conflict | Employee | Weekly dates include holiday → whole normal series rejected; choose dates or ask staff about exception |
| UC-15 | Monthly with 14-day limit | Employee | Until inside window → usually first only; later month manual; distant until rejected |
| UC-16 | Cancel one recurrence | Organizer/staff, eligible state | Open occurrence → reason → Cancel; other occurrences unchanged |
| UC-17 | Email check-in | Organizer holds valid link | Confirm between 10:00 and before 10:15 → Checked in; prior employee login not required |
| UC-18 | Missing email but present | Verified staff, Approved in window | Verify arrival → Manual check-in before deadline → audited; email tokens invalidated |
| UC-19 | No approval by start | Pending | Worker cancels at/after start; approval no longer possible; create new meeting |
| UC-20 | Missed check-in | Approved | Worker marks No show → room released; late link cannot revive; new booking if still free |
| UC-21 | Equipment repair | Verified staff, future free interval | Closures → reason/time → Block; overlap rejected |
| UC-22 | Retire room | Verified staff | Review bookings → Rooms Edit → clear Active → records preserved; manage meetings separately |
| UC-23 | Priority meeting | Verified staff | Resolve hold first → book on behalf → reason if policy exception → Approved; capacity/conflict still enforced |
| UC-24 | New Front Desk colleague | Verified staff, eligible mailbox | People → Active + Staff → Save → Email setup link; permissions equal administrators |
| UC-25 | Departing employee | Verified staff | Cancel/reassign future meetings separately → deactivate/revoke → sessions invalidated; history retained |
| UC-26 | Monthly usage review | Verified staff | Reports → range → counts/estimated utilization → Excel; percentages are not actual presence |
| UC-27 | Investigate changed booking | Verified staff | Audit actor/action + detail + IT logs if needed; read-only history |
| UC-28 | Email outage | Web/database operational | Saved state survives; queue waits/retries; IT checks mail/worker; deadline still applies |
| UC-29 | Confirm without staff review | Employee, free room with Requires approval unchecked | Submit valid team meeting → Approved immediately → confirmation and organizer check-in; normal capacity/conflict rules still apply |
| UC-30 | Change room approval requirement | Verified staff, room has existing Pending/Approved records | Rooms → change checkbox → saved/audited; saved bookings keep status; future submissions follow new policy |
| UC-31 | Resubmit a retained Pending request | Organizer/staff, future Pending in now-unchecked room | Unchanged save stays Pending; substantive valid edit becomes Approved and queues confirmation |

## Implemented scope and limitations

- First launch includes own calendar, the three-step booking flow with real schedule/series availability, internal/external/mixed meetings, recurring creation, approval, email notifications/check-in and staff administration.
- Room photos are optional staff uploads. They persist in the `room_media` Docker volume; database dumps contain file references, not the photo files. IT backs up/restores both together.
- HCL/Outlook/Exchange integration, calendar invitations/ICS and automatic sync are **deferred**. Email messages do not promise an entry in another calendar.
- Employees use links; staff use password plus email code. SSO, SMS/TOTP and independent employee numeric-code entry are not implemented.
- Recurrence is finite, limited to 15 occurrences; normal dates remain inside the horizon. No rolling monthly scheduler or bulk series action.
- Senior-management priority, refreshment fulfilment and equipment preparation are manual. No automatic displacement, catering integration or equipment inventory reservation.
- Only room intervals are conflict-protected. Attendee availability, concurrent meetings in different rooms for the same person, RSVP and waitlists are not managed.
- Room/user records are retained through inactivity; no normal hard-delete actions. Account/room/holiday changes do not retroactively cancel reservations.
- Reports use current policy/availability and verified scheduled time; they are not sensor occupancy or historical policy ledgers.
- The office uses the selected HTTP profile. A browser “Not secure” label is expected. Production safeguards remain enabled; local inbox/demo seeding are unavailable and forms require the exact site origin.
- Backups, restores, log rotation, monitoring, mailbox delivery, network access and retention are IT responsibilities described in operations documentation.
