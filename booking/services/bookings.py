import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.models import (
    AuditEvent,
    BookingAttendee,
    BookingPolicy,
    BookingSeries,
    CompanyHoliday,
    EmailToken,
    Reservation,
    Room,
    User,
)
from booking.services.email_login import normalized_employee_email
from booking.services.reservations import ReservationConflict, reserve_time

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")


class BookingError(Exception):
    pass


def occurrence_dates(first, last, frequency):
    if frequency not in {"none", "daily", "weekly", "monthly"}:
        raise BookingError("Choose a supported recurrence")
    if last < first:
        raise BookingError("The last date cannot be before the first date")
    if (last - first).days > 366:
        raise BookingError("A recurring series can cover at most one year")
    if frequency == "none":
        return [first]
    dates = []
    if frequency == "monthly":
        month_index = first.year * 12 + first.month - 1
        n = 0
        last_month_index = last.year * 12 + last.month - 1
        while month_index + n <= last_month_index:
            year, month_zero = divmod(month_index + n, 12)
            month = month_zero + 1
            day = min(first.day, calendar.monthrange(year, month)[1])
            current = first.replace(year=year, month=month, day=day)
            if current > last:
                break
            dates.append(current)
            n += 1
    else:
        step = timedelta(days=1 if frequency == "daily" else 7)
        current = first
        while current <= last:
            dates.append(current)
            if last - current < step:
                break
            current += step
    return dates


def policy_intervals(data, date, policy, *, override=False):
    start_local = datetime.combine(date, data["start_time"], LOCAL_TZ)
    end_local = datetime.combine(date, data["end_time"], LOCAL_TZ)
    now = timezone.localtime(timezone.now(), LOCAL_TZ)
    if end_local <= start_local:
        raise BookingError("End time must be after start time")
    if start_local <= now:
        raise BookingError("Choose a future start time")
    if not override:
        if date > now.date() + timedelta(days=policy.advance_days):
            raise BookingError(f"Bookings can be made at most {policy.advance_days} days ahead")
        if date.weekday() >= 5 or CompanyHoliday.objects.filter(date=date).exists():
            raise BookingError("This date is not a company working day")
        duration = int((end_local - start_local).total_seconds() // 60)
        if duration < policy.minimum_minutes or duration > policy.maximum_minutes:
            raise BookingError(
                f"Meeting length must be {policy.minimum_minutes}–{policy.maximum_minutes} minutes"
            )
        if data["start_time"] < policy.opens_at or data["end_time"] > policy.closes_at:
            raise BookingError("Choose a time within office hours")
        if any(
            (value.hour * 60 + value.minute) % policy.slot_minutes or value.second
            for value in (data["start_time"], data["end_time"])
        ):
            raise BookingError(f"Times must use {policy.slot_minutes}-minute increments")
    return start_local, end_local, start_local, end_local + timedelta(minutes=policy.gap_minutes)


def _organizer(actor, data, *, staff):
    email = data.get("organizer_email") if staff else ""
    if not email:
        return actor
    email = normalized_employee_email(email)
    if not email:
        raise BookingError("Use a WDN organizer email address")
    user, _ = User.objects.get_or_create(
        email__iexact=email,
        defaults={"email": email, "password": make_password(None)},
    )
    if not user.is_active:
        raise BookingError("This organizer is inactive")
    return user


def _attendees(reservation, addresses):
    BookingAttendee.objects.filter(reservation=reservation).delete()
    BookingAttendee.objects.bulk_create(
        [BookingAttendee(reservation=reservation, email=email) for email in addresses]
    )


def _capacity(room, data, organizer):
    count = (
        1
        + len([address for address in data["attendees"] if address != organizer.email])
        + data["external_attendee_count"]
    )
    if count > room.capacity:
        raise BookingError(f"This room seats {room.capacity} people; the meeting lists {count}")


def _common_fields(data):
    return {
        "title": data["title"],
        "description": data["description"],
        "meeting_type": data["meeting_type"],
        "guest_company_name": data["guest_company_name"],
        "external_attendee_count": data["external_attendee_count"],
        "department": data["department"],
        "refreshments_requested": data["refreshments_requested"],
        "front_desk_notes": data["front_desk_notes"],
        "override_reason": data.get("override_reason", ""),
    }


def create_booking(data, *, actor, staff=False):
    from booking.services.checkin import release_due_no_shows

    release_due_no_shows()
    return _create_booking(data, actor=actor, staff=staff)


@transaction.atomic
def _create_booking(data, *, actor, staff):
    from booking.services.notifications import queue_booking_event

    room = Room.objects.select_for_update().get(pk=data["room"].pk)
    if not room.is_active:
        raise BookingError("This room is inactive")
    organizer = _organizer(actor, data, staff=staff)
    _capacity(room, data, organizer)
    policy = BookingPolicy.objects.get(pk=1)
    last = data["until_date"] if data["recurrence"] != "none" else data["date"]
    override = staff and bool(data.get("override_reason"))
    if (
        last > timezone.localtime(timezone.now(), LOCAL_TZ).date() + timedelta(days=policy.advance_days)
        and not override
    ):
        raise BookingError(f"Occurrences must stay within the {policy.advance_days}-day booking window")
    dates = occurrence_dates(data["date"], last, data["recurrence"])
    if data["recurrence"] == "daily" and not override:
        holidays = set(
            CompanyHoliday.objects.filter(date__gte=data["date"], date__lte=last).values_list(
                "date", flat=True
            )
        )
        dates = [day for day in dates if day.weekday() < 5 and day not in holidays]
    if not dates:
        raise BookingError("This series contains no company working days")
    if len(dates) > 15:
        raise BookingError("This series has too many occurrences")
    intervals = [policy_intervals(data, day, policy, override=override) for day in dates]
    series = None
    if data["recurrence"] != "none":
        series = BookingSeries.objects.create(
            room=room,
            organizer=organizer,
            created_by=actor,
            frequency=data["recurrence"],
            first_date=dates[0],
            last_date=dates[-1],
        )
    created = []
    for start, end, occupied_from, occupied_until in intervals:
        try:
            booking = reserve_time(
                room_id=room.pk,
                occupied_from=occupied_from,
                occupied_until=occupied_until,
                starts_at=start,
                ends_at=end,
                kind=Reservation.Kind.BOOKING,
                status=Reservation.Status.CONFIRMED,
                organizer=organizer,
                created_by=actor,
                series=series,
                **_common_fields(data),
            )
        except ReservationConflict as exc:
            raise BookingError(
                f"Room unavailable on {timezone.localtime(start, LOCAL_TZ):%d %b %Y at %H:%M}"
            ) from exc
        _attendees(booking, data["attendees"])
        queue_booking_event(booking, "confirmation")
        AuditEvent.objects.create(
            actor=actor,
            action="booking_created",
            target_type="reservation",
            target_id=booking.pk,
            outcome="success",
            details={"room_id": room.pk, "on_behalf": organizer.pk != actor.pk},
        )
        created.append(booking)
    return created


def update_booking(booking_id, data, *, actor, staff=False):
    from booking.services.checkin import release_due_no_shows

    release_due_no_shows()
    return _update_booking(booking_id, data, actor=actor, staff=staff)


@transaction.atomic
def _update_booking(booking_id, data, *, actor, staff):
    from booking.services.notifications import queue_booking_event

    original_room_id = Reservation.objects.values_list("room_id", flat=True).get(
        pk=booking_id, kind=Reservation.Kind.BOOKING
    )
    requested_room_id = data["room"].pk
    locked_rooms = {
        room.pk: room
        for room in Room.objects.select_for_update()
        .filter(pk__in=[original_room_id, requested_room_id])
        .order_by("pk")
    }
    booking = Reservation.objects.select_for_update().get(pk=booking_id, kind=Reservation.Kind.BOOKING)
    if booking.room_id not in locked_rooms:
        raise BookingError("This booking changed while you were editing it. Reload it and try again")
    if booking.status != Reservation.Status.CONFIRMED:
        raise BookingError("Only upcoming confirmed bookings can be edited")
    if not staff and booking.organizer_id != actor.pk:
        raise BookingError("You cannot edit another employee's booking")
    old_attendees = list(booking.attendees.values_list("email", flat=True))
    old_organizer_email = booking.organizer.email
    new_room = locked_rooms.get(requested_room_id)
    if new_room is None or not new_room.is_active:
        raise BookingError("This room is inactive")
    organizer = _organizer(actor, data, staff=staff) if staff else booking.organizer
    _capacity(new_room, data, organizer)
    policy = BookingPolicy.objects.get(pk=1)
    start, end, occupied_from, occupied_until = policy_intervals(
        data, data["date"], policy, override=staff and bool(data.get("override_reason"))
    )
    conflict = (
        Reservation.objects.filter(
            room=new_room,
            status__in=["confirmed", "checked_in", "completed", "blocked"],
            occupied_from__lt=occupied_until,
            occupied_until__gt=occupied_from,
        )
        .exclude(pk=booking.pk)
        .exists()
    )
    if conflict:
        raise BookingError("This room is unavailable for the selected time")
    for field, value in {
        "room": new_room,
        "organizer": organizer,
        "starts_at": start,
        "ends_at": end,
        "occupied_from": occupied_from,
        "occupied_until": occupied_until,
        **_common_fields(data),
    }.items():
        setattr(booking, field, value)
    try:
        with transaction.atomic():
            booking.save()
    except IntegrityError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == "23P01":
            raise BookingError("This room is unavailable for the selected time") from exc
        raise
    _attendees(booking, data["attendees"])
    EmailToken.objects.filter(
        purpose=EmailToken.Purpose.CHECK_IN, reservation=booking, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    queue_booking_event(booking, "change", extra_recipients=[*old_attendees, old_organizer_email])
    AuditEvent.objects.create(
        actor=actor,
        action="booking_modified",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
        details={"room_id": new_room.pk, "on_behalf": organizer.pk != actor.pk},
    )
    return booking


@transaction.atomic
def cancel_booking(booking_id, *, actor, staff=False, reason="Cancelled by organizer"):
    from booking.services.notifications import queue_booking_event

    booking = Reservation.objects.select_for_update().get(pk=booking_id, kind=Reservation.Kind.BOOKING)
    if not staff and booking.organizer_id != actor.pk:
        raise BookingError("You cannot cancel another employee's booking")
    if booking.status not in [Reservation.Status.CONFIRMED, Reservation.Status.CHECKED_IN]:
        raise BookingError("This booking is already closed")
    booking.status = Reservation.Status.CANCELLED
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason[:240]
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    EmailToken.objects.filter(
        purpose=EmailToken.Purpose.CHECK_IN, reservation=booking, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())
    queue_booking_event(booking, "cancellation")
    AuditEvent.objects.create(
        actor=actor,
        action="booking_cancelled",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
        details={"reason": reason[:100]},
    )
    return booking
