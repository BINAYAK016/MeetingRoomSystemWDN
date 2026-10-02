from collections import Counter, defaultdict
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from booking.models import BookingPolicy, CompanyHoliday, Reservation, Room

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")


def _union(intervals):
    merged = []
    for start, end in sorted(intervals):
        if start >= end:
            continue
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(end, merged[-1][1]))
        else:
            merged.append((start, end))
    return merged


def _subtract(windows, closures):
    remaining = []
    closures = _union(closures)
    closure_index = 0
    for start, end in windows:
        cursor = start
        while closure_index < len(closures) and closures[closure_index][1] <= start:
            closure_index += 1
        index = closure_index
        while index < len(closures) and closures[index][0] < end:
            closed_start, closed_end = closures[index]
            if closed_start > cursor:
                remaining.append((cursor, min(closed_start, end)))
            cursor = max(cursor, closed_end)
            if cursor >= end:
                break
            index += 1
        if cursor < end:
            remaining.append((cursor, end))
    return remaining


def _minutes(intervals):
    return sum((end - start).total_seconds() / 60 for start, end in intervals)


def _intersection_minutes(first, second):
    first = _union(first)
    second = _union(second)
    left = right = 0
    total = 0.0
    while left < len(first) and right < len(second):
        start = max(first[left][0], second[right][0])
        end = min(first[left][1], second[right][1])
        if start < end:
            total += (end - start).total_seconds() / 60
        if first[left][1] <= second[right][1]:
            left += 1
        else:
            right += 1
    return total


def report_data(start, end):
    """Report local-date bookings and estimated utilization of bookable hours.

    Booking counts use each meeting's Nepal start date. Utilization intersects
    checked-in/completed meeting intervals with the selected working windows,
    including meetings that began before the range. Current booking policy,
    holiday and active closure records define availability; historical policy
    and room activation changes are not stored by this application.
    """
    if end < start or (end - start).days > 366:
        raise ValueError("Choose a valid range of up to one year")
    range_start = datetime.combine(start, time.min, LOCAL_TZ)
    range_end = datetime.combine(end, time.min, LOCAL_TZ) + timedelta(days=1)
    records = list(
        Reservation.objects.filter(
            kind=Reservation.Kind.BOOKING,
            starts_at__gte=range_start,
            starts_at__lt=range_end,
        )
        .select_related("room", "organizer")
        .order_by("starts_at", "pk")
    )
    by_room = defaultdict(list)
    departments = Counter()
    organizers = Counter()
    for item in records:
        by_room[item.room_id].append(item)
        departments[item.department or "Unspecified"] += 1
        organizers[item.organizer.email] += 1

    verified_by_room = defaultdict(list)
    verified_statuses = (Reservation.Status.CHECKED_IN, Reservation.Status.COMPLETED)
    for item in records:
        if item.status in verified_statuses:
            verified_by_room[item.room_id].append((item.starts_at, item.ends_at))
    carry_in = Reservation.objects.filter(
        kind=Reservation.Kind.BOOKING,
        status__in=verified_statuses,
        starts_at__lt=range_start,
        ends_at__gt=range_start,
    ).values_list("room_id", "starts_at", "ends_at")
    for room_id, begins, finishes in carry_in:
        verified_by_room[room_id].append((begins, finishes))

    holidays = set(
        CompanyHoliday.objects.filter(date__gte=start, date__lte=end).values_list("date", flat=True)
    )
    policy = BookingPolicy.objects.get(pk=1)
    working_windows = []
    for offset in range((end - start).days + 1):
        day = start + timedelta(days=offset)
        if day.weekday() < 5 and day not in holidays:
            working_windows.append(
                (
                    datetime.combine(day, policy.opens_at, LOCAL_TZ),
                    datetime.combine(day, policy.closes_at, LOCAL_TZ),
                )
            )

    closures_by_room = defaultdict(list)
    closures = Reservation.objects.filter(
        kind=Reservation.Kind.BLOCK,
        status=Reservation.Status.BLOCKED,
        starts_at__lt=range_end,
        ends_at__gt=range_start,
    ).values_list("room_id", "starts_at", "ends_at")
    for room_id, begins, finishes in closures:
        closures_by_room[room_id].append((begins, finishes))

    room_rows = []
    for room in Room.objects.all().order_by("name", "pk"):
        subset = by_room[room.pk]
        bookable_windows = _subtract(working_windows, closures_by_room[room.pk])
        available_minutes = _minutes(bookable_windows)
        occupied_minutes = _intersection_minutes(verified_by_room[room.pk], bookable_windows)
        statuses = Counter(item.status for item in subset)
        room_rows.append(
            {
                "room": room,
                "bookings": len(subset),
                "completed": statuses[Reservation.Status.COMPLETED],
                "cancelled": statuses[Reservation.Status.CANCELLED],
                "no_shows": statuses[Reservation.Status.NO_SHOW],
                "utilization": round(occupied_minutes * 100 / available_minutes, 1)
                if available_minutes
                else 0,
                "available_minutes": round(available_minutes, 2),
                "occupied_minutes": round(occupied_minutes, 2),
            }
        )
    room_rows.sort(key=lambda item: (-item["bookings"], item["room"].name))
    return (
        records,
        room_rows,
        sorted(departments.items(), key=lambda item: (-item[1], item[0])),
        sorted(organizers.items(), key=lambda item: (-item[1], item[0])),
    )
