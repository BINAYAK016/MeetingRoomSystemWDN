import calendar
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.utils import timezone

from booking.models import (
    ACTIVE_RESERVATION_STATUSES,
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
from booking.services.auth_security import staff_session_verified
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
        raise BookingError("Use a company employee organizer email address")
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


def _require_actor(actor, *, staff=False, current=None):
    current = current or User.objects.filter(pk=actor.pk).first()
    if not actor.is_authenticated or current is None or not current.is_active:
        raise BookingError("An active employee account is required")
    if staff and not current.is_staff:
        raise BookingError("Staff access is required")


def _locked_users(*ids):
    # Role/deactivation updates use the same row lock. NO KEY UPDATE allows FK
    # inserts (audit/booking/email) without creating User -> Room lock inversions.
    return {
        user.pk: user
        for user in User.objects.select_for_update(no_key=True).filter(pk__in=ids).order_by("pk")
    }


def _require_verified_staff(actor, request, *, current=None):
    current = current or _locked_users(actor.pk).get(actor.pk)
    _require_actor(actor, staff=True, current=current)
    if (
        not current.is_active
        or not current.is_staff
        or request is None
        or request.user.pk != actor.pk
        or request.session.get("staff_auth_version") != current.auth_version
        or not staff_session_verified(request)
    ):
        raise BookingError("Verified staff sign-in is required")


def _supersede_booking_mail(booking):
    from booking.models import Notification

    Notification.objects.filter(reservation=booking, status__in=["pending", "failed", "sending"]).update(
        status=Notification.Status.SKIPPED, last_error="", lease_token=None, lease_expires_at=None
    )
    EmailToken.objects.filter(
        purpose=EmailToken.Purpose.CHECK_IN, reservation=booking, consumed_at__isnull=True
    ).update(consumed_at=timezone.now())


def create_booking(data, *, actor, staff=False):
    from booking.services.checkin import release_due_no_shows

    _require_actor(actor, staff=staff)
    release_due_no_shows()
    return _create_booking(data, actor=actor, staff=staff)


@transaction.atomic
def _create_booking(data, *, actor, staff):
    from booking.services.notifications import queue_booking_event

    organizer = _organizer(actor, data, staff=staff)
    users = _locked_users(actor.pk, organizer.pk)
    _require_actor(actor, staff=staff, current=users.get(actor.pk))
    organizer = users[organizer.pk]
    if not organizer.is_active:
        raise BookingError("This organizer is inactive")
    room = Room.objects.select_for_update().get(pk=data["room"].pk)
    if not room.is_active:
        raise BookingError("This room is inactive")
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
                status=Reservation.Status.APPROVED if staff else Reservation.Status.PENDING,
                approved_by=actor if staff else None,
                approved_at=timezone.now() if staff else None,
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
        queue_booking_event(booking, "confirmation" if staff else "request")
        AuditEvent.objects.create(
            actor=actor,
            action="booking_created",
            target_type="reservation",
            target_id=booking.pk,
            outcome="success",
            details={"room_id": room.pk, "on_behalf": organizer.pk != actor.pk, "status": booking.status},
        )
        created.append(booking)
    return created


def update_booking(booking_id, data, *, actor, staff=False):
    from booking.services.checkin import release_due_no_shows

    _require_actor(actor, staff=staff)
    release_due_no_shows()
    return _update_booking(booking_id, data, actor=actor, staff=staff)


@transaction.atomic
def _update_booking(booking_id, data, *, actor, staff):
    from booking.services.notifications import queue_booking_event

    original = Reservation.objects.values("room_id", "organizer_id").get(
        pk=booking_id, kind=Reservation.Kind.BOOKING
    )
    if not staff and original["organizer_id"] != actor.pk:
        raise BookingError("You cannot edit another employee's booking")
    organizer = _organizer(actor, data, staff=staff) if staff else actor
    users = _locked_users(actor.pk, organizer.pk)
    _require_actor(actor, staff=staff, current=users.get(actor.pk))
    organizer = users[organizer.pk]
    if not organizer.is_active:
        raise BookingError("This organizer is inactive")
    original_room_id = original["room_id"]
    requested_room_id = data["room"].pk
    locked_rooms = {
        room.pk: room
        for room in Room.objects.select_for_update()
        .filter(pk__in=[original_room_id, requested_room_id])
        .order_by("pk")
    }
    booking = Reservation.objects.select_for_update().get(pk=booking_id, kind=Reservation.Kind.BOOKING)
    if booking.room_id not in locked_rooms or booking.organizer_id != original["organizer_id"]:
        raise BookingError("This booking changed while you were editing it. Reload it and try again")
    if (
        booking.status not in [Reservation.Status.PENDING, Reservation.Status.APPROVED]
        or booking.starts_at <= timezone.now()
    ):
        raise BookingError("Only upcoming pending or approved bookings can be edited")
    if not staff and booking.organizer_id != actor.pk:
        raise BookingError("You cannot edit another employee's booking")
    old_attendees = list(booking.attendees.values_list("email", flat=True))
    old_organizer_email = booking.organizer.email
    new_room = locked_rooms.get(requested_room_id)
    if new_room is None or not new_room.is_active:
        raise BookingError("This room is inactive")
    _capacity(new_room, data, organizer)
    policy = BookingPolicy.objects.get(pk=1)
    start, end, occupied_from, occupied_until = policy_intervals(
        data, data["date"], policy, override=staff and bool(data.get("override_reason"))
    )
    conflict = (
        Reservation.objects.filter(
            room=new_room,
            status__in=ACTIVE_RESERVATION_STATUSES,
            occupied_from__lt=occupied_until,
            occupied_until__gt=occupied_from,
        )
        .exclude(pk=booking.pk)
        .exists()
    )
    if conflict:
        raise BookingError("This room is unavailable for the selected time")
    changes = {
        "room": new_room,
        "organizer": organizer,
        "starts_at": start,
        "ends_at": end,
        "occupied_from": occupied_from,
        "occupied_until": occupied_until,
        **_common_fields(data),
    }
    substantive_change = any(getattr(booking, field) != value for field, value in changes.items()) or set(
        old_attendees
    ) != set(data["attendees"])
    if not substantive_change:
        return booking
    booking.revision += 1
    if not staff and booking.status == Reservation.Status.APPROVED:
        booking.status = Reservation.Status.PENDING
        booking.approved_by = None
        booking.approved_at = None
    for field, value in changes.items():
        setattr(booking, field, value)
    try:
        with transaction.atomic():
            booking.save()
    except IntegrityError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == "23P01":
            raise BookingError("This room is unavailable for the selected time") from exc
        raise
    _attendees(booking, data["attendees"])
    _supersede_booking_mail(booking)
    event = "request" if booking.status == Reservation.Status.PENDING else "change"
    queue_booking_event(
        booking, event, extra_recipients=[*old_attendees, old_organizer_email] if event == "change" else ()
    )
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

    _require_actor(actor, staff=staff, current=_locked_users(actor.pk).get(actor.pk))
    booking = Reservation.objects.select_for_update().get(pk=booking_id, kind=Reservation.Kind.BOOKING)
    if not staff and booking.organizer_id != actor.pk:
        raise BookingError("You cannot cancel another employee's booking")
    if booking.status not in [
        Reservation.Status.PENDING,
        Reservation.Status.APPROVED,
        Reservation.Status.CHECKED_IN,
    ]:
        raise BookingError("This booking is already closed")
    booking.status = Reservation.Status.CANCELLED
    booking.revision += 1
    booking.cancelled_at = timezone.now()
    booking.cancellation_reason = reason[:240]
    booking.save(update_fields=["status", "revision", "cancelled_at", "cancellation_reason", "updated_at"])
    _supersede_booking_mail(booking)
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


@transaction.atomic
def approve_booking(booking_id, *, actor, request):
    from booking.services.notifications import queue_booking_event

    initial = Reservation.objects.values("room_id", "organizer_id").get(pk=booking_id, kind="booking")
    users = _locked_users(actor.pk, initial["organizer_id"])
    _require_verified_staff(actor, request, current=users.get(actor.pk))
    organizer = users.get(initial["organizer_id"])
    if organizer is None or not organizer.is_active:
        raise BookingError("The organizer must be active before approval")
    room = Room.objects.select_for_update().get(pk=initial["room_id"])
    booking = (
        Reservation.objects.select_for_update(of=("self",))
        .select_related("room", "organizer")
        .get(pk=booking_id, kind="booking")
    )
    if booking.room_id != room.pk or booking.organizer_id != organizer.pk:
        raise BookingError("This request changed. Reload it before approving")
    if booking.status != Reservation.Status.PENDING:
        raise BookingError("Only pending booking requests can be approved")
    if booking.starts_at <= timezone.now():
        raise BookingError("A booking must be approved before its start time")
    if not room.is_active or not booking.organizer.is_active:
        raise BookingError("The room and organizer must be active before approval")
    booking.status = Reservation.Status.APPROVED
    booking.approved_by = actor
    booking.approved_at = timezone.now()
    booking.revision += 1
    booking.save(update_fields=["status", "approved_by", "approved_at", "revision", "updated_at"])
    _supersede_booking_mail(booking)
    queue_booking_event(booking, "confirmation")
    AuditEvent.objects.create(
        actor=actor,
        action="booking_approved",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
    )
    return booking


@transaction.atomic
def reject_booking(booking_id, *, actor, request, reason):
    from booking.services.notifications import queue_booking_event

    _require_verified_staff(actor, request)
    if not isinstance(reason, str) or not reason.strip() or len(reason.strip()) > 500:
        raise BookingError("Enter a rejection reason of up to 500 characters")
    booking = Reservation.objects.select_for_update().get(pk=booking_id, kind="booking")
    if booking.status != Reservation.Status.PENDING:
        raise BookingError("Only pending booking requests can be rejected")
    booking.status = Reservation.Status.REJECTED
    booking.rejected_by = actor
    booking.rejected_at = timezone.now()
    booking.rejection_reason = reason.strip()
    booking.revision += 1
    booking.save(
        update_fields=["status", "rejected_by", "rejected_at", "rejection_reason", "revision", "updated_at"]
    )
    _supersede_booking_mail(booking)
    queue_booking_event(booking, "rejection")
    AuditEvent.objects.create(
        actor=actor,
        action="booking_rejected",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
        details={"reason": booking.rejection_reason[:100]},
    )
    return booking
