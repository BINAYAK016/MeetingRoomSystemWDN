import hashlib
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from booking.models import AuditEvent, BookingPolicy, EmailToken, Reservation


class CheckInError(Exception):
    pass


def _no_show(booking, now):
    from booking.services.notifications import queue_booking_event

    booking.status = Reservation.Status.NO_SHOW
    booking.cancelled_at = now
    booking.cancellation_reason = "No check-in before the deadline"
    booking.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    EmailToken.objects.filter(reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True).update(consumed_at=now)
    queue_booking_event(booking, "no_show")
    AuditEvent.objects.create(action="booking_no_show", target_type="reservation", target_id=booking.pk, outcome="success")


def release_due_no_shows(now=None):
    now = now or timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    cutoff = now - timedelta(minutes=policy.check_in_minutes)
    count = 0
    ids = Reservation.objects.filter(kind=Reservation.Kind.BOOKING, status=Reservation.Status.CONFIRMED, starts_at__lte=cutoff).values_list("pk", flat=True)[:100]
    for booking_id in ids:
        with transaction.atomic():
            booking = Reservation.objects.select_for_update().get(pk=booking_id)
            if booking.status == Reservation.Status.CONFIRMED and booking.starts_at + timedelta(minutes=policy.check_in_minutes) <= now:
                _no_show(booking, now)
                count += 1
    return count


@transaction.atomic
def confirm_checkin(raw_token, *, actor=None):
    if not raw_token or len(raw_token) > 128:
        raise CheckInError("This check-in link is unavailable")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    initial = EmailToken.objects.filter(token_hash=token_hash, purpose=EmailToken.Purpose.CHECK_IN).first()
    if initial is None:
        raise CheckInError("This check-in link is unavailable")
    booking = Reservation.objects.select_for_update().get(pk=initial.reservation_id)
    token = EmailToken.objects.select_for_update().get(pk=initial.pk)
    now = timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    deadline = booking.starts_at + timedelta(minutes=policy.check_in_minutes)
    if booking.status != Reservation.Status.CONFIRMED or token.consumed_at or token.expires_at <= now:
        raise CheckInError("This check-in link has expired or was already used")
    if now < booking.starts_at:
        raise CheckInError("Check-in opens when the meeting starts")
    if now >= deadline:
        raise CheckInError("The check-in deadline has passed")
    booking.status = Reservation.Status.CHECKED_IN
    booking.checked_in_at = now
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])
    EmailToken.objects.filter(reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True).update(consumed_at=now)
    from booking.services.notifications import queue_booking_event
    queue_booking_event(booking, "check_in")
    AuditEvent.objects.create(actor=actor or booking.organizer, action="booking_checked_in", target_type="reservation", target_id=booking.pk, outcome="success")
    return booking


@transaction.atomic
def manual_checkin(booking_id, *, actor):
    from booking.services.notifications import queue_booking_event

    booking = Reservation.objects.select_for_update().get(pk=booking_id)
    now = timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    if booking.status != Reservation.Status.CONFIRMED or not booking.starts_at <= now < booking.starts_at + timedelta(minutes=policy.check_in_minutes):
        raise CheckInError("This booking is outside the check-in window")
    booking.status = Reservation.Status.CHECKED_IN
    booking.checked_in_at = now
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])
    EmailToken.objects.filter(reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True).update(consumed_at=now)
    queue_booking_event(booking, "check_in")
    AuditEvent.objects.create(actor=actor, action="staff_checked_in", target_type="reservation", target_id=booking.pk, outcome="success")
    return booking


def complete_finished(now=None):
    now = now or timezone.now()
    return Reservation.objects.filter(status=Reservation.Status.CHECKED_IN, ends_at__lte=now).update(status=Reservation.Status.COMPLETED)
