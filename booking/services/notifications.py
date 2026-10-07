import hashlib
import logging
import secrets
import uuid
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.db.models import Q
from django.urls import reverse
from django.utils import timezone

from booking.models import BookingPolicy, EmailToken, Notification, Reservation, User
from booking.services.mail_delivery import deliver_mail, safe_subject

MAX_ATTEMPTS = 5
logger = logging.getLogger(__name__)


def queue_booking_event(booking, event, *, extra_recipients=()):
    labels = {
        "request": "submitted and awaiting administrator approval",
        "confirmation": "approved",
        "rejection": "rejected",
        "change": "changed",
        "cancellation": "cancelled",
        "no_show": "released after no check-in",
        "check_in": "checked in",
    }
    recipients = {booking.organizer.email, *extra_recipients}
    if event not in {"request", "rejection"}:
        recipients.update(booking.attendees.values_list("email", flat=True))
    recipients.update(User.objects.filter(is_staff=True, is_active=True).values_list("email", flat=True))
    local_start = timezone.localtime(booking.starts_at).strftime("%A %d %B %Y, %H:%M")
    local_end = timezone.localtime(booking.ends_at).strftime("%H:%M")
    subject = safe_subject(f"Meeting room booking {labels[event]}: {booking.title}")
    body = (
        f"Your meeting room booking was {labels[event]}.\n\n"
        f"Meeting: {booking.title}\nRoom: {booking.room.name} ({booking.room.location}, floor {booking.room.floor})\n"
        f"When: {local_start}–{local_end} Nepal time\nOrganizer: {booking.organizer.email}\n\n"
        "Open the Meeting Rooms app for current details."
        + (f"\n\nRejection reason: {booking.rejection_reason}" if event == "rejection" else "")
        + (f"\n\nCancellation reason: {booking.cancellation_reason}" if event == "cancellation" else "")
        + (
            "\n\nThis request holds the room while awaiting administrator approval. It is not approved yet."
            if event == "request"
            else ""
        )
    )
    Notification.objects.bulk_create(
        [
            Notification(
                reservation=booking,
                reservation_revision=booking.revision,
                recipient_email=email,
                event_type=event,
                subject=subject,
                body=body,
                next_attempt_at=timezone.now(),
            )
            for email in sorted(recipients)
            if email
        ]
    )


def queue_conflict_notice(email, room_name, meeting_date, start_time):
    Notification.objects.create(
        recipient_email=email,
        event_type="conflict",
        subject="WDN meeting room time unavailable",
        body=(
            f"Your attempted booking for {room_name} on {meeting_date} at {start_time} could not be saved "
            "because the room was unavailable. Please select another room or time in WDN Meeting Rooms."
        ),
        next_attempt_at=timezone.now(),
    )


def queue_due_reminders(now=None):
    now = now or timezone.now()
    queued = 0
    ids = Reservation.objects.filter(
        status=Reservation.Status.APPROVED,
        kind=Reservation.Kind.BOOKING,
        starts_at__gt=now,
        starts_at__lte=now + timedelta(hours=1),
    ).values_list("pk", flat=True)
    for booking_id in ids:
        with transaction.atomic():
            booking = (
                Reservation.objects.select_for_update(of=("self",))
                .select_related("organizer", "room")
                .get(pk=booking_id)
            )
            if (
                booking.status != Reservation.Status.APPROVED
                or not now < booking.starts_at <= now + timedelta(hours=1)
            ):
                continue
            marker = f"start={booking.starts_at.isoformat()}"
            recipients = {booking.organizer.email}
            recipients.update(booking.attendees.values_list("email", flat=True))
            recipients.update(
                User.objects.filter(is_staff=True, is_active=True).values_list("email", flat=True)
            )
            for email in recipients:
                if Notification.objects.filter(
                    reservation=booking,
                    reservation_revision=booking.revision,
                    event_type="reminder",
                    body=marker,
                    recipient_email=email,
                ).exists():
                    continue
                Notification.objects.create(
                    reservation=booking,
                    reservation_revision=booking.revision,
                    recipient_email=email,
                    event_type="reminder",
                    subject=safe_subject(f"Meeting room reminder: {booking.title}"),
                    body=marker,
                    next_attempt_at=now,
                )
                queued += 1
    return queued


def _checkin_instructions(booking):
    now = timezone.now()
    policy = BookingPolicy.objects.get(pk=1)
    if booking.status != Reservation.Status.APPROVED or now >= booking.starts_at + timedelta(
        minutes=policy.check_in_minutes
    ):
        return ""
    raw = secrets.token_urlsafe(32)
    EmailToken.objects.create(
        user=booking.organizer,
        reservation=booking,
        email=booking.organizer.email,
        purpose=EmailToken.Purpose.CHECK_IN,
        token_hash=hashlib.sha256(raw.encode()).hexdigest(),
        expires_at=booking.starts_at + timedelta(minutes=policy.check_in_minutes),
    )
    url = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("checkin-link", args=[raw])
    return (
        f"\n\nCheck in using this secure link after the meeting starts: {url}\n\n"
        f"Check-in closes {policy.check_in_minutes} minutes after the start."
    )


@transaction.atomic
def _delivery_body(notification):
    if notification.reservation_id is None:
        return notification.body
    if not Notification.objects.filter(
        pk=notification.pk, lease_token=notification.lease_token, status=Notification.Status.SENDING
    ).exists():
        return None
    booking = (
        Reservation.objects.select_for_update(of=("self",))
        .select_related("room", "organizer")
        .get(pk=notification.reservation_id)
    )
    if (
        notification.reservation_revision is not None
        and notification.reservation_revision != booking.revision
    ):
        return None
    allowed = {
        "request": {Reservation.Status.PENDING},
        "confirmation": {
            Reservation.Status.APPROVED,
            Reservation.Status.CHECKED_IN,
            Reservation.Status.COMPLETED,
        },
        "change": {Reservation.Status.APPROVED, Reservation.Status.CHECKED_IN, Reservation.Status.COMPLETED},
        "rejection": {Reservation.Status.REJECTED},
        "cancellation": {Reservation.Status.CANCELLED},
        "no_show": {Reservation.Status.NO_SHOW},
        "check_in": {Reservation.Status.CHECKED_IN, Reservation.Status.COMPLETED},
        "reminder": {Reservation.Status.APPROVED},
    }
    if notification.event_type in allowed and booking.status not in allowed[notification.event_type]:
        return None
    if notification.event_type not in {"reminder", "confirmation", "change"}:
        return notification.body
    if notification.reservation_revision is None and notification.created_at < booking.updated_at:
        return None
    if notification.event_type in {"confirmation", "change"}:
        return notification.body + (
            _checkin_instructions(booking) if notification.recipient_email == booking.organizer.email else ""
        )
    policy = BookingPolicy.objects.get(pk=1)
    if (
        booking.status != Reservation.Status.APPROVED
        or notification.body != f"start={booking.starts_at.isoformat()}"
        or timezone.now() >= booking.starts_at + timedelta(minutes=policy.check_in_minutes)
    ):
        return None
    base = (
        f"Meeting '{booking.title}' starts at {timezone.localtime(booking.starts_at):%H:%M} Nepal time "
        f"in {booking.room.name}."
    )
    if notification.recipient_email == booking.organizer.email:
        return base + _checkin_instructions(booking)
    return base + "\n\nThe organizer will receive a secure check-in link."


def send_due_notifications(now=None, limit=30):
    now = now or timezone.now()
    if settings.EMAIL_BACKEND == "booking.mail_backends.DisabledEmailBackend":
        return 0
    sent = 0
    # A process may die after claiming its final attempt. Make that failure visible.
    Notification.objects.filter(status=Notification.Status.SENDING, attempts__gte=MAX_ATTEMPTS).filter(
        Q(lease_expires_at__lte=now) | Q(lease_expires_at__isnull=True, next_attempt_at__lte=now)
    ).update(
        status=Notification.Status.FAILED,
        lease_token=None,
        lease_expires_at=None,
        last_error="WorkerInterrupted",
    )
    for _ in range(limit):
        with transaction.atomic():
            notification = (
                Notification.objects.select_for_update(skip_locked=True)
                .filter(attempts__lt=MAX_ATTEMPTS)
                .filter(
                    Q(
                        status__in=[Notification.Status.PENDING, Notification.Status.FAILED],
                        next_attempt_at__lte=now,
                    )
                    | Q(status=Notification.Status.SENDING, lease_expires_at__lte=now)
                    | Q(
                        status=Notification.Status.SENDING,
                        lease_expires_at__isnull=True,
                        next_attempt_at__lte=now,
                    )
                )
                .order_by("next_attempt_at", "pk")
                .first()
            )
            if notification is None:
                break
            notification.status = Notification.Status.SENDING
            notification.attempts += 1
            notification.lease_token = uuid.uuid4()
            notification.lease_expires_at = now + timedelta(minutes=5)
            notification.next_attempt_at = now + timedelta(minutes=5)
            notification.save(
                update_fields=["status", "attempts", "next_attempt_at", "lease_token", "lease_expires_at"]
            )

        try:
            body = _delivery_body(notification)
            if body is not None:
                deliver_mail(notification.subject, body, [notification.recipient_email])
                notification.status = Notification.Status.SENT
                notification.sent_at = timezone.now()
                sent += 1
            else:
                notification.status = Notification.Status.SKIPPED
                notification.sent_at = None
            notification.last_error = ""
        except Exception as exc:
            notification.status = Notification.Status.FAILED
            notification.last_error = type(exc).__name__[:240]
            notification.next_attempt_at = timezone.now() + timedelta(
                minutes=min(60, 2**notification.attempts)
            )
            logger.warning(
                "Notification %s failed on attempt %s (%s)",
                notification.pk,
                notification.attempts,
                type(exc).__name__,
            )
        Notification.objects.filter(pk=notification.pk, lease_token=notification.lease_token).update(
            status=notification.status,
            sent_at=notification.sent_at,
            last_error=notification.last_error,
            next_attempt_at=notification.next_attempt_at,
            lease_token=None,
            lease_expires_at=None,
        )
    return sent
