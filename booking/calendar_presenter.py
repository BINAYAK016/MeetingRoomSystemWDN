"""Calendar periods, privacy-safe events and actionable room availability."""

from calendar import Calendar, monthrange
from datetime import datetime, time, timedelta
from urllib.parse import urlencode
from zoneinfo import ZoneInfo

from django.urls import reverse
from django.utils import timezone

from booking.meeting_access import with_meeting_membership
from booking.models import ACTIVE_RESERVATION_STATUSES, CompanyHoliday, Reservation, Room

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")


def _calendar_url(day, view, room_id):
    query = {"date": day.isoformat(), "view": view}
    if room_id:
        query["room"] = room_id
    return f"{reverse('calendar')}?{urlencode(query)}"


def _booking_url(day, room_id="", start=None):
    query = {"date": day.isoformat()}
    if room_id:
        query["room"] = room_id
    if start is not None:
        query["start"] = start.strftime("%H:%M")
    return f"{reverse('booking-new')}?{urlencode(query)}"


def _month_shift(day, offset):
    index = day.year * 12 + day.month - 1 + offset
    year, month = divmod(index, 12)
    month += 1
    return day.replace(year=year, month=month, day=min(day.day, monthrange(year, month)[1]))


def _period_days(selected, view):
    if view == "month":
        weeks = Calendar(firstweekday=0).monthdatescalendar(selected.year, selected.month)
        return [day for week in weeks for day in week]
    if view == "week":
        first = selected - timedelta(days=selected.weekday())
        return [first + timedelta(days=offset) for offset in range(7)]
    return [selected]


def _period_title(selected, view, days):
    if view == "month":
        return selected.strftime("%B %Y")
    if view == "day":
        return f"{selected:%A}, {selected.day} {selected:%B %Y}"
    first, last = days[0], days[-1]
    if first.year != last.year:
        return f"{first.day} {first:%b %Y} – {last.day} {last:%b %Y}"
    if first.month != last.month:
        return f"{first.day} {first:%b} – {last.day} {last:%b %Y}"
    return f"{first.day} – {last.day} {last:%B %Y}"


def _date_reasons(day, today, policy, holidays):
    if day in holidays:
        closed = f"Company holiday: {holidays[day]}"
    elif day.weekday() >= 5:
        closed = "Office closed for the weekend"
    else:
        closed = ""
    if closed:
        return closed, closed
    if day < today:
        return "", "Past date"
    if day > today + timedelta(days=policy.advance_days):
        return "", f"Outside the {policy.advance_days}-day booking window"
    return "", ""


def _time_label(start, end, day):
    end_label = "24:00" if end.date() > day and end.time() == time.min else end.strftime("%H:%M")
    return f"{start:%H:%M} – {end_label}"


def _event_for_day(item, day, room, user_id, staff):
    """Never put inaccessible reservation identifiers or private values in template data."""
    first = datetime.combine(day, time.min, LOCAL_TZ)
    last = first + timedelta(days=1)
    start = timezone.localtime(item.starts_at, LOCAL_TZ)
    end = timezone.localtime(item.ends_at, LOCAL_TZ)
    own = item.organizer_id == user_id
    attending = bool(item.is_attendee)
    accessible = own or attending or staff
    event = {
        "room_id": room.pk,
        "room_label": room.name,
        "room_location": f"{room.location} · Floor {room.floor}",
        "url": "",
        "relation_label": "",
        "is_short": False,
        "own": own,
        "attending": attending,
    }
    if end <= first or start >= last:
        # An occupied interval can enter an adjacent day only through its preparation gap.
        clipped_start = max(timezone.localtime(item.occupied_from, LOCAL_TZ), first)
        clipped_end = min(timezone.localtime(item.occupied_until, LOCAL_TZ), last)
        event.update(
            title="Meeting buffer",
            status_label="Preparation gap",
            css_class="calendar-event-buffer",
            kind="buffer",
        )
    else:
        clipped_start, clipped_end = max(start, first), min(end, last)
        if item.kind == Reservation.Kind.BLOCK:
            event.update(
                title=item.block_reason if staff else "Room closed",
                status_label="Room closed",
                css_class="calendar-event-closed",
                kind="closure",
                url=reverse("staff-blocks") if staff else "",
            )
        else:
            pending = item.status == Reservation.Status.PENDING
            title = item.title if accessible else "Pending approval" if pending else "Busy"
            relation = "Your meeting" if own else "Invited meeting" if attending else ""
            style = "pending" if pending else "own" if own else "invited" if attending else "other"
            event.update(
                title=title,
                status_label=item.get_status_display()
                if accessible
                else "Pending approval"
                if pending
                else "Busy",
                css_class=f"calendar-event-{style}",
                kind="booking",
                relation_label=relation,
                url=reverse("booking-detail", args=[item.pk]) if accessible else "",
                is_short=end - start < timedelta(minutes=30),
            )
    event.update(
        starts_at=clipped_start,
        ends_at=clipped_end,
        time_label=_time_label(clipped_start, clipped_end, day),
        continues_from_previous_day=start < first,
        continues_to_next_day=end > last,
    )
    return event


def _slot_rows(day, rooms, by_room, policy, now, reason, user_id, staff):
    rows = []
    cursor = datetime.combine(day, policy.opens_at, LOCAL_TZ)
    closing = datetime.combine(day, policy.closes_at, LOCAL_TZ)
    previous = {}
    events = {
        item.pk: _event_for_day(item, day, room, user_id, staff)
        for room in rooms
        for item in by_room[room.pk]
        if item.occupied_from < closing and item.occupied_until > cursor
    }
    while cursor < closing:
        end = min(cursor + timedelta(minutes=policy.slot_minutes), closing)
        cells = []
        for room in rooms:
            occupying = next(
                (
                    item
                    for item in by_room[room.pk]
                    if item.occupied_from < end and item.occupied_until > cursor
                ),
                None,
            )
            unavailable = reason
            if not unavailable and cursor <= now:
                unavailable = "Start time has passed"
            if not unavailable and cursor + timedelta(minutes=policy.minimum_minutes) > closing:
                unavailable = "Not enough time before closing"
            if not unavailable and occupying is None:
                minimum_end = cursor + timedelta(minutes=policy.minimum_minutes + policy.gap_minutes)
                if any(
                    item.occupied_from < minimum_end and item.occupied_until > cursor
                    for item in by_room[room.pk]
                ):
                    unavailable = "Not enough time for a meeting and buffer"
            event = events.get(occupying.pk) if occupying else None
            before_meeting = bool(occupying and end <= occupying.starts_at)
            after_meeting = bool(occupying and cursor >= occupying.ends_at)
            buffer = before_meeting or after_meeting
            identity = (occupying.pk, "buffer" if buffer else "meeting") if occupying else None
            can_open = bool(
                occupying
                and occupying.kind == Reservation.Kind.BOOKING
                and (occupying.organizer_id == user_id or occupying.is_attendee or staff)
            )
            if buffer:
                first = datetime.combine(day, time.min, LOCAL_TZ)
                last = first + timedelta(days=1)
                buffer_start = occupying.occupied_from if before_meeting else occupying.ends_at
                buffer_end = occupying.starts_at if before_meeting else occupying.occupied_until
                clipped_start = max(timezone.localtime(buffer_start, LOCAL_TZ), first)
                clipped_end = min(timezone.localtime(buffer_end, LOCAL_TZ), last)
                event = {
                    **event,
                    "title": "Meeting buffer",
                    "status_label": "Preparation gap",
                    "css_class": "calendar-event-buffer",
                    "kind": "buffer",
                    "is_short": False,
                    "relation_label": "",
                    "url": reverse("booking-detail", args=[occupying.pk]) if can_open else "",
                    "starts_at": clipped_start,
                    "ends_at": clipped_end,
                    "time_label": _time_label(clipped_start, clipped_end, day),
                    "continues_from_previous_day": buffer_start < first,
                    "continues_to_next_day": buffer_end > last,
                }
            available = occupying is None and not unavailable
            cell = {
                "room": room,
                "occupied": event,
                "own": bool(occupying and occupying.organizer_id == user_id),
                "attending": bool(occupying and occupying.is_attendee),
                "can_open": can_open,
                "unavailable_reason": unavailable,
                "available": available,
                "booking_url": _booking_url(day, room.pk, cursor) if available else "",
                "show_event": bool(occupying and previous.get(room.pk) != identity),
                "continuation": bool(occupying and previous.get(room.pk) == identity),
                "buffer": buffer,
            }
            cells.append(cell)
            previous[room.pk] = identity
        rows.append({"time": cursor, "cells": cells})
        cursor = end
    return rows


def build_calendar_context(request, policy, *, staff, now=None):
    now = now or timezone.now()
    today = timezone.localtime(now, LOCAL_TZ).date()
    try:
        selected = datetime.strptime(request.GET.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        selected = today
    if abs((selected - today).days) > 366:
        selected = today
    view = request.GET.get("view", "month")
    if view not in ("month", "week", "day"):
        view = "month"

    # One stable room snapshot is shared by selectors, reservation queries and every cell.
    rooms = list(Room.objects.filter(is_active=True).order_by("location", "floor", "name"))
    raw_room = request.GET.get("room", "")
    selected_room = next((room for room in rooms if str(room.pk) == raw_room), None)
    room_id = str(selected_room.pk) if selected_room else ""
    calendar_rooms = [selected_room] if selected_room else rooms
    days = _period_days(selected, view)
    first = datetime.combine(days[0], time.min, LOCAL_TZ)
    last = datetime.combine(days[-1] + timedelta(days=1), time.min, LOCAL_TZ)
    holidays = dict(
        CompanyHoliday.objects.filter(date__gte=days[0], date__lte=days[-1]).values_list("date", "name")
    )
    bookings = list(
        with_meeting_membership(
            Reservation.objects.filter(
                room_id__in=[room.pk for room in calendar_rooms],
                occupied_from__lt=last,
                occupied_until__gt=first,
                status__in=ACTIVE_RESERVATION_STATUSES,
            ),
            request.user,
        )
        .select_related("room")
        .order_by("starts_at", "room_id", "pk")
    )
    by_room = {room.pk: [] for room in calendar_rooms}
    for item in bookings:
        by_room[item.room_id].append(item)

    day_data = []
    slots = []
    date_reason = ""
    for day in days:
        day_start = datetime.combine(day, time.min, LOCAL_TZ)
        day_end = day_start + timedelta(days=1)
        closed, reason = _date_reasons(day, today, policy, holidays)
        events = [
            _event_for_day(item, day, room, request.user.pk, staff)
            for room in calendar_rooms
            for item in by_room[room.pk]
            if item.occupied_from < day_end and item.occupied_until > day_start
        ]
        events.sort(key=lambda event: (event["starts_at"], event["room_label"]))
        day_slots = []
        if not reason or view == "day":
            day_slots = _slot_rows(day, calendar_rooms, by_room, policy, now, reason, request.user.pk, staff)
        first_available = next(
            (cell for row in day_slots for cell in row["cells"] if cell["available"]), None
        )
        day_data.append(
            {
                "date": day,
                "is_today": day == today,
                "outside_month": day.month != selected.month or day.year != selected.year,
                "closed_reason": closed,
                "booking_reason": reason,
                "day_url": _calendar_url(day, "day", room_id),
                "new_booking_url": first_available["booking_url"] if first_available else "",
                "events": events,
                "visible_events": events[:3],
                "more_events": events[3:],
                "extra_count": max(0, len(events) - 3),
            }
        )
        if view == "day":
            slots, date_reason = day_slots, reason

    previous = (
        _month_shift(selected, -1)
        if view == "month"
        else selected - timedelta(days=7 if view == "week" else 1)
    )
    following = (
        _month_shift(selected, 1)
        if view == "month"
        else selected + timedelta(days=7 if view == "week" else 1)
    )

    def bounded_url(day):
        return _calendar_url(day, view, room_id) if abs((day - today).days) <= 366 else ""

    day_columns = (
        [
            {
                "room": room,
                "events": [event for event in day_data[0]["events"] if event["room_id"] == room.pk],
                "slots": [{"time": row["time"], **row["cells"][index]} for row in slots],
            }
            for index, room in enumerate(calendar_rooms)
        ]
        if view == "day"
        else []
    )
    selected_data = next(item for item in day_data if item["date"] == selected)
    default_booking_url = reverse("booking-new")
    if room_id:
        default_booking_url += f"?{urlencode({'room': room_id})}"
    calendar = {
        "title": _period_title(selected, view, days),
        "subtitle": (
            f"{selected_room.name if selected_room else 'All meeting rooms'} · Nepal time · "
            f"{policy.opens_at:%H:%M}–{policy.closes_at:%H:%M}"
        ),
        "selected_room_id": room_id,
        "previous_url": bounded_url(previous),
        "next_url": bounded_url(following),
        "today_url": _calendar_url(today, view, room_id),
        "month_url": _calendar_url(selected, "month", room_id),
        "week_url": _calendar_url(selected, "week", room_id),
        "day_url": _calendar_url(selected, "day", room_id),
        "new_booking_url": selected_data["new_booking_url"] or default_booking_url,
        "month_weeks": [{"days": day_data[index : index + 7]} for index in range(0, len(day_data), 7)]
        if view == "month"
        else [],
        "week_days": day_data if view == "week" else [],
        "day_columns": day_columns,
        "timeline_hours": [row["time"] for row in slots if row["time"].minute == 0],
        "day_events": day_data[0]["events"] if view == "day" else [],
        "weekday_labels": ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"),
    }
    return {
        "calendar": calendar,
        "view": view,
        "selected": selected,
        "rooms": rooms,
        "calendar_rooms": calendar_rooms,
        "policy": policy,
        "staff": staff,
        "slots": slots,
        "date_unavailable_reason": date_reason,
    }
