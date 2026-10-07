import hashlib
import re
from datetime import timedelta

from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from booking.models import AuditEvent, BookingPolicy, EmailToken, Reservation


class CheckInError(Exception):
    pass


def _no_show(booking, now):
    from booking.services.notifications import queue_booking_event

    booking.status = Reservation.Status.NO_SHOW
    booking.revision += 1
    booking.cancelled_at = now
    booking.cancellation_reason = "No check-in before the deadline"
    booking.save(update_fields=["status", "revision", "cancelled_at", "cancellation_reason", "updated_at"])
    EmailToken.objects.filter(
        reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True
    ).update(consumed_at=now)
    from booking.services.bookings import _supersede_booking_mail

    _supersede_booking_mail(booking)
    queue_booking_event(booking, "no_show")
    AuditEvent.objects.create(
        action="booking_no_show", target_type="reservation", target_id=booking.pk, outcome="success"
    )


def release_due_pending_requests(now=None):
    from booking.services.bookings import _supersede_booking_mail
    from booking.services.notifications import queue_booking_event

    now = now or timezone.now()
    count = 0
    ids = Reservation.objects.filter(
        kind=Reservation.Kind.BOOKING, status=Reservation.Status.PENDING, starts_at__lte=now
    ).values_list("pk", flat=True)[:100]
    for booking_id in ids:
        with transaction.atomic():
            booking = Reservation.objects.select_for_update().get(pk=booking_id)
            if booking.status != Reservation.Status.PENDING or booking.starts_at > now:
                continue
            booking.status = Reservation.Status.CANCELLED
            booking.cancelled_at = now
            booking.cancellation_reason = "Approval window expired before the meeting started"
            booking.revision += 1
            booking.save(
                update_fields=["status", "revision", "cancelled_at", "cancellation_reason", "updated_at"]
            )
            _supersede_booking_mail(booking)
            queue_booking_event(booking, "cancellation")
            AuditEvent.objects.create(
                action="booking_request_expired",
                target_type="reservation",
                target_id=booking.pk,
                outcome="success",
            )
            count += 1
    return count


def release_due_no_shows(now=None):
    now = now or timezone.now()
    release_due_pending_requests(now=now)
    policy = BookingPolicy.objects.get(pk=1)
    cutoff = now - timedelta(minutes=policy.check_in_minutes)
    count = 0
    ids = Reservation.objects.filter(
        kind=Reservation.Kind.BOOKING, status=Reservation.Status.APPROVED, starts_at__lte=cutoff
    ).values_list("pk", flat=True)[:100]
    for booking_id in ids:
        with transaction.atomic():
            booking = Reservation.objects.select_for_update().get(pk=booking_id)
            if (
                booking.status == Reservation.Status.APPROVED
                and booking.starts_at + timedelta(minutes=policy.check_in_minutes) <= now
            ):
                _no_show(booking, now)
                count += 1
    return count


@sensitive_variables("raw_token")
def confirm_checkin(raw_token, *, actor=None):
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 128:
        raise CheckInError("This check-in link is unavailable")
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return confirm_checkin_hash(token_hash, actor=actor)


@transaction.atomic
def confirm_checkin_hash(token_hash, *, actor=None):
    """Consume a session-staged digest; public email links always carry raw tokens."""
    if not isinstance(token_hash, str) or re.fullmatch(r"[0-9a-f]{64}", token_hash) is None:
        raise CheckInError("This check-in link is unavailable")
    initial = EmailToken.objects.filter(token_hash=token_hash, purpose=EmailToken.Purpose.CHECK_IN).first()
    if initial is None:
        raise CheckInError("This check-in link is unavailable")
    from booking.services.bookings import _locked_users
    from booking.services.email_login import normalized_employee_email

    organizer_id = Reservation.objects.values_list("organizer_id", flat=True).get(pk=initial.reservation_id)
    organizer = _locked_users(organizer_id).get(organizer_id)
    if organizer is None or not organizer.is_active or normalized_employee_email(organizer.email) is None:
        raise CheckInError("This organizer account is unavailable")
    booking = Reservation.objects.select_for_update().get(pk=initial.reservation_id)
    token = EmailToken.objects.select_for_update().get(pk=initial.pk)
    if (
        booking.organizer_id != organizer.pk
        or token.user_id != organizer.pk
        or token.email.lower() != organizer.email.lower()
    ):
        raise CheckInError("This check-in link is unavailable")
    now = timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    deadline = booking.starts_at + timedelta(minutes=policy.check_in_minutes)
    if booking.status != Reservation.Status.APPROVED or token.consumed_at or token.expires_at <= now:
        raise CheckInError("This check-in link has expired or was already used")
    if now < booking.starts_at:
        raise CheckInError("Check-in opens when the meeting starts")
    if now >= deadline:
        raise CheckInError("The check-in deadline has passed")
    booking.status = Reservation.Status.CHECKED_IN
    booking.checked_in_at = now
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])
    EmailToken.objects.filter(
        reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True
    ).update(consumed_at=now)
    from booking.services.notifications import queue_booking_event

    queue_booking_event(booking, "check_in")
    AuditEvent.objects.create(
        actor=actor or booking.organizer,
        action="booking_checked_in",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
    )
    return booking


@transaction.atomic
def manual_checkin(booking_id, *, actor):
    from booking.services.bookings import BookingError, _locked_users, _require_actor
    from booking.services.notifications import queue_booking_event

    try:
        _require_actor(actor, staff=True, current=_locked_users(actor.pk).get(actor.pk))
    except BookingError as exc:
        raise CheckInError("Active staff access is required") from exc

    try:
        booking = Reservation.objects.select_for_update().get(pk=booking_id, kind=Reservation.Kind.BOOKING)
    except Reservation.DoesNotExist as exc:
        raise CheckInError("This booking is unavailable") from exc
    now = timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    if (
        booking.status != Reservation.Status.APPROVED
        or not booking.starts_at <= now < booking.starts_at + timedelta(minutes=policy.check_in_minutes)
    ):
        raise CheckInError("This booking is outside the check-in window")
    booking.status = Reservation.Status.CHECKED_IN
    booking.checked_in_at = now
    booking.save(update_fields=["status", "checked_in_at", "updated_at"])
    EmailToken.objects.filter(
        reservation=booking, purpose=EmailToken.Purpose.CHECK_IN, consumed_at__isnull=True
    ).update(consumed_at=now)
    queue_booking_event(booking, "check_in")
    AuditEvent.objects.create(
        actor=actor,
        action="staff_checked_in",
        target_type="reservation",
        target_id=booking.pk,
        outcome="success",
    )
    return booking


def complete_finished(now=None):
    now = now or timezone.now()
    return Reservation.objects.filter(status=Reservation.Status.CHECKED_IN, ends_at__lte=now).update(
        status=Reservation.Status.COMPLETED, updated_at=now
    )
