# Employee guide

**Meeting Booking System (MBS)**
**Transgate Tech | Binayak Bhandari**
Checked against application source on **8 October 2026**.

This guide explains employee use of **http://mbs.wdn.com.np** on the office network. Use a company email ending in **@wdn.com.np** or **@transgate.com.np**. All displayed meeting times are **Nepal time (NPT)**. For the complete behavior reference see [Features and use cases](features-and-use-cases.md); staff workflows are in the [staff guide](staff-guide.md).

## Quick start

1. Open [Employee sign-in](http://mbs.wdn.com.np/sign-in/).
2. Enter company email, request the link, open it within 15 minutes and press **Continue to workspace**.
3. Open **My profile** and set name/department.
4. Find a room using **Rooms** and a time using **Calendar**.
5. Submit **New booking**. A room marked **Staff approval required** starts **Pending approval**; wait for staff. A room marked **Automatic approval** starts **Approved** immediately.
6. At meeting start, open the organizer check-in link in the approved email and press **Check in now** before the deadline.
7. Use **My meetings** for meetings you organize or attend, status and history. Invited meetings are read-only.

## Navigation

| Menu / page | What to do there |
| --- | --- |
| [Overview](http://mbs.wdn.com.np/) | Room count, upcoming meetings, pending count and current booking window |
| [Rooms](http://mbs.wdn.com.np/rooms/) | Search room, seat count, location and facilities; read instructions |
| [Calendar](http://mbs.wdn.com.np/calendar/) | Day/week occupancy and available starts |
| [My meetings](http://mbs.wdn.com.np/bookings/mine/) | Upcoming or History for meetings you organize or attend; filter by role, status or search |
| [New booking](http://mbs.wdn.com.np/bookings/new/) | Schedule & details → Attendees → Review & confirm for one meeting or recurring occurrences |
| [My profile](http://mbs.wdn.com.np/profile/) | Your name and department |
| Staff desk | Management interface; separate staff password/code authentication required |
| Sign out | End this browser's session |

## 1. Sign in using company email

### First or returning sign-in

1. Connect to the office network, or the company-approved connection that reaches the internal site.
2. Open **http://mbs.wdn.com.np/sign-in/** in Chrome or Edge with cookies enabled. Keep this hostname throughout the workflow.
3. Enter your exact company email. Capitalization is normalized; either approved domain is accepted.
4. Submit and check that mailbox. The page says **Check your email** if delivery is configured.
5. Open the link within **15 minutes**. It opens the confirmation page.
6. Press **Continue to workspace**. You are now signed in; the overview shows your account email.

An account is created on first successful confirmation. There is no employee password to remember. Possession of the emailed one-time link verifies access to that mailbox. Opening it alone does not complete sign-in, so mail scanners that inspect links do not normally consume it.

Each completed session lasts **eight hours**. Use **Sign out** on shared devices. An account deactivated by staff cannot sign in. Account permissions/password changes can end an existing session and require fresh authentication.

### If the link does not work

| Situation | Action |
| --- | --- |
| Expired or already used link | Return to sign-in and request a new one; a completed link cannot be reused |
| No mail arrives | Check Junk/quarantine and spelling/domain; contact Front Desk or IT |
| Repeated requests | Limit is three per address per 15 minutes; wait for the window rather than repeatedly submitting |
| “Email unavailable” | IT must configure/repair SMTP; there is no production local test inbox |
| “Let's start fresh” / session check | Reopen the form at the same hostname, keep cookies enabled and retry; ask IT to inspect CSRF logs if persistent |
| Staff pages require login again | Employee email-link authentication does not unlock staff powers; use staff password plus email code |

The generic mail-request screen does not guarantee a message was sent, accepted or delivered. Share the screen text, time and ordinary page path with IT; keep email sign-in/check-in links and codes private. See [troubleshooting](troubleshooting.md) for the server-side checks.

## 2. Set your profile

1. Choose **My profile**.
2. Enter first name, last name and department, for example “Operations”.
3. Save and check the **Your profile has been saved** message.

Department is used as the initial value on future booking forms. You can change it on a meeting where needed. Updating your profile does not rewrite the department already saved on earlier bookings. Email and access flags cannot be changed from this page; contact staff.

## 3. Choose a room

1. Open **Rooms**.
2. Enter a search such as “3” for floor or a room name/description term.
3. Set **Minimum seats**, for example `6`.
4. Select a location or facility, for example “Projector”, when offered.
5. Press **Find rooms**. Use **Reset** to clear filters; use pagination for additional results.
6. Open **Room details** to read capacity, facilities, description and instructions.
7. Use **Book this room** to preselect it, or **View availability** to compare times.

Only active rooms are listed. A room's listed facility is a descriptive label; contact Front Desk if you need to verify equipment is ready. Employees cannot edit room records. If no room matches, widen filters or ask Front Desk about available rooms.

## 4. Read the calendar

1. Open **Calendar**.
2. Select a date and **Day** or **Week**, then press **Show**. **Today** resets the selected date.
3. In day view, find the row/time and room column.
4. **Available +** opens the booking wizard with room/date/start preselected. Check the proposed duration/end and adjust if needed.
5. In week view, select a day to see its detailed slots.

| Calendar marking | Meaning |
| --- | --- |
| Available + | A permitted start for at least a minimum meeting and required buffer appears free at page load |
| Your meeting | Occupied by a meeting you organize; select to open details |
| Invited meeting | You are listed as an attendee; select for read-only details |
| Unavailable | Another booking/request, closure or buffer occupies the interval; details remain private |
| Outside rule / past / holiday explanation | This start cannot be booked normally; read the displayed reason |

Calendar availability is checked again on submission. Another person may hold the slot after you load the page. Staff can see month view; employees use day/week. A signed-in employee listed as an attendee may open that meeting's details; unrelated employees see only occupancy without title, notes or attendee details. Invitation never grants editing, cancellation, approval or organizer check-in rights.

## 5. Request a single internal meeting

The following is an illustrative request. Choose a **future company working date within the current booking window** and an active room with enough seats; do not submit the placeholder addresses as real invitations.

| Field | Example |
| --- | --- |
| Room | An available eight-seat room |
| Date | A future working Thursday |
| Start / End | 10:00 / 11:00 |
| Title | Team planning |
| Description | Review next week's work and outstanding actions |
| Meeting type | Internal |
| Additional guests without email addresses | 0 |
| Department | Operations |
| Attendees | `colleague@wdn.com.np`, `teammate@transgate.com.np` (replace with real colleagues) |
| Refreshments requested | Select only if needed |
| Special requirements | Projector needed; please check remote batteries |
| Recurrence | One meeting |
| Until date | Leave blank |

1. Open **New booking**, or use the room/calendar link.
2. In **Schedule & details**, choose a date, duration and start time. Use **Custom** for explicit start/end. All times are Nepal time; the choices follow current office rules.
3. Wait for the room cards to update. Check capacity, location, facilities and any real photo; select a room marked available for the selected schedule.
4. Enter meeting title and information, select **Internal**, set refreshments to Yes/No, and add special requirements. Keep Repeat meeting as **One meeting**.
5. Select **Next: attendees**. Type at least two letters from the start of a colleague's email, first name or last name and choose a directory suggestion, or enter complete addresses manually separated by commas or new lines. Duplicate addresses are normalized and removed; the organizer is already included. Enter `0` additional guests and check the displayed headcount fits the room.
6. Continue to **Review & confirm**. Read the room, date/time, meeting details and attendee list. Use **Edit** or **Back** to correct them without restarting.
7. Press **Submit booking request** for a room requiring review, or **Confirm booking** for an automatically approved room, once. Availability and the current room policy are checked again while saving.
8. On success, check the saved status. A room requiring approval shows **Pending approval** and holds the room/time; an unchecked room shows **Approved** immediately.
9. If Pending, wait for staff approval before treating the meeting as confirmed. If Approved, read the confirmation/check-in instructions. Follow the status in **My meetings**.

### Choose attendees from the employee directory

The Attendees field suggests active employee accounts registered in MBS after at least **two characters** are typed in the current address. Up to **eight matches** are displayed, with name and email. Choose with the mouse, or use Up/Down arrows and Enter; Escape closes the choices. Selection adds a removable attendee chip without submitting the booking. For an unlisted/external address, type the full address and press **Add attendee +** or Enter, or paste several separated addresses. Remove a chip with its remove control. Duplicate addresses and the organizer are counted once, and headcount updates immediately. A valid complete email still in the input is added when you press Next; an incomplete/invalid address blocks progression until corrected.

The directory uses the approved company domains. A colleague who has not yet completed company-email sign-in may not appear; enter their full address manually or ask them to sign in. Deactivated accounts do not appear. External guest addresses can still be typed manually. Suggestions do not check a person's calendar, guarantee they are free or grant staff access. With JavaScript unavailable, use complete addresses in the normal text field.

Room cards and the review screen show the room's approval requirement. Both reviewed and immediately confirmed bookings must satisfy the same capacity, availability and booking rules; staff creation uses its own verified staff path.

The room preview does not reserve space. If the schedule changes, wait for its updated result; an intervening booking can still be rejected at final submission. Field/general errors preserve your entries so you can correct and retry. A photo is optional; a room without a photo can be booked normally.

With JavaScript disabled or unavailable, the page presents one native form with room/date/start/end and all meeting/attendee fields. Enter end time explicitly and submit the same request; server rules and approval still apply. The three steps, duration buttons and live availability preview require JavaScript.

### Normal initial rules

Staff can change these under Rules. Current form/calendar messages and office policy take precedence over this default table.

| Rule | Initial setting |
| --- | --- |
| Working days / hours | Monday–Friday, 09:00–17:00; configured holidays excluded |
| Meeting length | 30–120 minutes |
| Start/end increments | 15 minutes |
| Gap after end | 15 minutes |
| Advance limit | 14 calendar days |
| Check-in deadline | Before 15 minutes after start |

A 10:00–11:00 meeting holds the room until 11:15 under the default gap. The organizer counts as one person. Listed attendees other than organizer and the external attendee count are added to room capacity. Max 50 distinct listed addresses are permitted. End must be after start, on the same date; past start times are rejected.

### Common submission failures

| Message / cause | How to resolve |
| --- | --- |
| Room unavailable | Another hold/booking/closure or required gap conflicts; choose another room/time |
| Room seats fewer than listed | Choose a larger room or correct attendee/guest count |
| Meeting length outside permitted range | Adjust start/end to current duration rules |
| Outside office hours or increments | Choose aligned times inside current hours |
| Not a company working day | Choose weekday not listed as a holiday; staff can review a justified exception |
| Too far ahead | Choose a date within current horizon |
| Invalid attendee email | Correct the identified address; text names alone are not email addresses |

A failed submission does not create a booking. On a failed edit, the previously saved booking remains. Refresh the calendar when correcting a conflict; do not create repeated duplicate requests for the same planned meeting.

## 6. Request an external or mixed meeting

1. In Schedule & details, select **External** for a guest meeting, or **Internal + External** for a mixed meeting. Both require a guest company name.
2. Enter guest company name, for example **Example Partners**.
3. In Attendees, enter the number of additional guests who are not individually listed by email.
4. List colleague/guest email addresses that should receive approved meeting notifications.
5. Select refreshments if needed and enter preparation needs in **Special requirements**, review, then submit.

Example: organizer + two listed colleagues + three unlisted guests = **six people**. If a guest has already been counted as a listed email attendee, do not count them again as an unlisted external attendee. External addresses may receive attendee notifications, but cannot use account sign-in unless their domain is in the employee allowlist. Refreshments are a request for Front Desk to handle manually, not an automatically fulfilled order.

## 7. Create a recurring series

1. In Schedule & details, enter first date, time and common meeting details.
2. Set **Repeat meeting** to **Daily**, **Weekly** or **Monthly**.
3. Choose an inclusive **Last date in series** inside the current booking horizon.
4. Wait for availability: each room must fit every eligible occurrence, not just the first. A conflict on a later date also makes that room unavailable.
5. Add attendees, then review the actual occurrence dates/times in **Review & confirm**. Daily skips appear in the resulting list; no hidden later months are reserved.
6. Submit; the detail page opens the first created occurrence.
7. Open **My meetings** to inspect all occurrences. Each starts Pending if the selected room requires approval, otherwise Approved. Pending occurrences need individual review; every Approved occurrence has its own organizer check-in. Listed employees see the same occurrences as invited meetings.

| Example | Expected behavior |
| --- | --- |
| Daily 09:00–09:30 through a future working week | Creates eligible weekdays; skips holidays/weekends |
| Weekly next Thursday and the following Thursday | Creates both if dates are working days and both slots free |
| Monthly with until date inside next two weeks | Usually creates first occurrence only; book later months manually when eligible |
| Any requested occurrence conflicts | Entire series fails; no partial series is saved |
| Weekly/monthly date lands on holiday/weekend | Entire normal request rejected; alter dates or ask staff about an exception |
| Until date three months away with 14-day rule | Rejected; the application does not truncate a distant series automatically |

At most **15 occurrences** are allowed in one creation. Monthly dates use the original day number, clamped to shorter month-end when necessary. The application does not extend a series automatically. Editing/cancelling one occurrence leaves other occurrences unchanged. There is no whole-series edit/cancel button.

## 8. Follow approval and status

Open **My meetings** and select the meeting title. The detail page shows room, date/time, requester, request time, department, guests, attendees, description, preparation notes, state and available actions. A role label distinguishes **You’re organizing** from **You’re invited**. Listed attendees can read current details and decisions, including a Pending request, but cannot manage it.

| State | Meaning / next step |
| --- | --- |
| Pending approval | Slot held; contact Front Desk before start if approval is delayed |
| Approved | Meeting confirmed; organizer receives check-in instructions |
| Rejected | Read staff reason; slot released; make a new request if needed |
| Checked in | Arrival confirmed; meeting becomes Completed after scheduled end |
| Completed | Historical record; cannot edit/cancel normally |
| Cancelled | Released by cancellation or approval-window expiry; reason shown |
| No show | Deadline missed; room released; old check-in link cannot restore it |

**Upcoming** lists active Pending/Approved/Checked in meetings whose end has not passed. **History & all meetings** shows all accessible meeting records, including future records in other states; it is not exclusively past meetings. Use **All my meetings**, **I’m organizing** or **I’m invited** to narrow your role, then search by meeting/room/location/organizer or filter by status. Press **Find meetings**; **Reset** clears those filters. The list shows 25 meetings per page and keeps the selected filters. Summary cards show all your upcoming active meetings, how many of those are pending, and the upcoming organized/invited split; changing the list filters does not change those cards. The same meeting is listed once if you are both organizer and listed attendee.

Attendee visibility matches your signed-in email against the saved attendee list, ignoring capitalization. If the organizer adds you, the meeting appears when you reload; if they remove you, read access ends immediately. Emails already received are not recalled. An unrelated employee cannot open private details by guessing the booking ID. The organizer and verified staff retain management rights; being invited grants read-only access.

A request still Pending at meeting start is automatically cancelled because its approval window expired. Staff changing the room to **Automatic approval** does not automatically approve saved Pending requests. They remain Pending until staff review or a substantive valid edit; an unchanged save keeps their state.

## 9. Edit or cancel

### Edit

1. Open a meeting you organize from **My meetings**.
2. For a future Pending or Approved record, select **Edit booking**.
3. Use the same three steps to adjust fields, review, and press **Save booking changes**. The original date/start/end, room and meeting information are prefilled; recurrence controls are omitted because this edits one occurrence.
4. Check the resulting state and confirmation message.

A substantive employee edit uses the **selected room's current approval requirement**. Checked means **Pending** for staff review; unchecked means **Approved** immediately. This applies to a change of room as well as details, times or attendees, and invalidates earlier check-in links. An unchanged save retains the state, including an existing Pending request after staff unchecked its room. Current room capacity, availability and policy apply to edits. Started, Checked in, Completed, Rejected, Cancelled and No show records cannot be edited through normal workflow.

### Cancel

1. Open the eligible Pending, Approved or Checked in record.
2. Enter a cancellation reason, for example **Client visit postponed**.
3. Select **Cancel booking** and confirm the prompt.
4. Check the Cancelled state and reason.

The room is released; history remains and event emails are queued. Cancellation affects one occurrence only. There is no undo button; make a new request if needed.

## 10. Check in at meeting start

1. Find the **Check in** button in the latest approved confirmation/change email or reminder sent to the organizer. The plain-text version provides the same private link.
2. Open it at the scheduled start time.
3. Press **Check in now** before the configured deadline.
4. Check the **You're all set** confirmation and meeting/room name.

For a 10:00 meeting with the default rule, check-in opens at **10:00** and closes at **10:15**. The deadline is exclusive: at 10:15 it is too late. Opening the link before start is allowed, but confirming early is rejected; keep the page and use **Try check-in again** after start.

The email button opens the secure confirmation flow; it does not record arrival inside the email itself. Confirm in the browser with **Check in now**. This deliberate second step prevents mail scanners or a preview from marking someone present. Check-in uses possession of the emailed organizer link; a prior employee login is not required. It still requires browser cookies and the confirmation button. Attendees do not receive the organizer's private check-in link or gain check-in permission from My meetings. A used or superseded link will fail, and a cancelled/rejected/No show booking cannot be checked in.

If mail is missing while attendees have arrived, contact Front Desk **before the deadline**. Verified staff can perform Manual check-in during the same window. Email problems do not automatically extend it. A missed deadline marks the record No show and releases the room on the next successful worker reconciliation, normally about every 30 seconds.

## 11. Notifications and support

You receive submission/decision/change/cancellation/check-in/no-show messages for your meetings. After approval, listed attendees and active staff receive the corresponding meeting events; unapproved submission and rejection are sent to organizer/staff, not attendees. Reminder scheduling begins within one hour of an Approved start and depends on worker/relay delivery; it is not guaranteed at precisely 60 minutes before.

Messages provide a branded HTML layout with a clear event heading, meeting summary, Nepal-time schedule and relevant action. Mail clients that block or do not render HTML can use the plain-text alternative. Approved organizer messages show the private Check in action when valid; messages to current company-domain participants and active staff link to the meeting without that private action. External guests and former participants with neither current participation nor active staff access receive **Contact organizer** and the current organizer's email instead. A change notice does not restore a removed recipient's meeting access or make an external address eligible to sign in. The supplied Transgate wordmark is attached within the message rather than loaded from a tracking/external image server. Do not forward sign-in, password setup or organizer check-in links.

A saved booking remains saved during a mail outage. Use the application state as the record of the meeting and ask staff/IT about missing email. HCL/Outlook calendar integration and calendar invitation files are deferred; an MBS email does not automatically create another calendar entry.

When reporting an issue, provide:

- Ordinary page path, such as `/bookings/mine/`, and approximate Nepal time.
- Action attempted, expected result and visible error text.
- Booking ID, if relevant, and whether it was Pending/Approved/another state.
- Browser name and whether a fresh page/reload reproduces it.

Do not send passwords, sign-in/check-in/setup links, email codes or `.env` contents. Contact Front Desk for booking decisions/room preparation and IT for access, mail or server issues. Diagnostic commands are in [troubleshooting](troubleshooting.md).
