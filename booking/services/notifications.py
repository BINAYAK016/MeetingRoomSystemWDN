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
from booking.services.email_login import normalized_employee_email
from booking.services.email_templates import public_url, render_email
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
        f"View meeting: {public_url('booking-detail', booking.pk)}"
        + (f"\n\nRejection reason: {booking.rejection_reason}" if event == "rejection" else "")
        + (f"\n\nCancellation reason: {booking.cancellation_reason}" if event == "cancellation" else "")
        + (
            "\n\nThis booking is marked No show. The room was released because the organizer did not check in before the deadline."
            if event == "no_show"
            else ""
        )
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


def _checkin_link(booking):
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
    return settings.PUBLIC_BASE_URL.rstrip("/") + reverse("checkin-link", args=[raw])


def _checkin_instructions(booking, *, url=None):
    url = _checkin_link(booking) if url is None else url
    if not url:
        return ""
    policy = BookingPolicy.objects.get(pk=1)
    start = timezone.localtime(booking.starts_at)
    deadline = start + timedelta(minutes=policy.check_in_minutes)
    return (
        f"\n\nCheck in using this secure link after the meeting starts: {url}\n\n"
        f"Check-in opens at {start:%H:%M} and closes at {deadline:%H:%M} Nepal time on {start:%d %B %Y}. "
        f"Check-in closes {policy.check_in_minutes} minutes after the start. "
        "Open the link and confirm your arrival. If you do not check in by the deadline, "
        "the booking is marked No show and the room is released. Do not forward this organizer link."
    )


def _recipient_can_view_meeting(booking, recipient_email):
    email = normalized_employee_email(recipient_email)
    if email is None:
        return False
    return (
        email == booking.organizer.email.casefold()
        or booking.attendees.filter(email__iexact=email).exists()
        or User.objects.filter(email__iexact=email, is_active=True, is_staff=True).exists()
    )


def _booking_email_html(notification, booking, checkin_url, *, can_view_meeting=None):
    if can_view_meeting is None:
        can_view_meeting = _recipient_can_view_meeting(booking, notification.recipient_email)
    events = {
        "request": (
            "A meeting request is waiting.",
            "The room is held while staff review this request. The meeting is not approved yet.",
            "Awaiting approval",
            "amber",
        ),
        "confirmation": (
            "Your meeting is confirmed.",
            "The room is reserved. Here are the details for your meeting.",
            "Confirmed",
            "green",
        ),
        "reminder": (
            "Your meeting starts soon.",
            "Everything you need for your upcoming meeting, in one place.",
            "Meeting reminder",
            "navy",
        ),
        "change": (
            "The meeting details have changed.",
            "Please use the latest schedule and room details below.",
            "Updated",
            "navy",
        ),
        "rejection": (
            "This request was not approved.",
            "The room hold has been released. You can choose another room or time.",
            "Not approved",
            "red",
        ),
        "cancellation": (
            "This meeting has been cancelled.",
            "The reservation has ended and the room is available for other bookings.",
            "Cancelled",
            "red",
        ),
        "no_show": (
            "The room has been released.",
            "The organizer did not check in before the deadline. The booking is marked No show and the room has been released.",
            "No show",
            "red",
        ),
        "check_in": (
            "You're checked in. Have a good meeting.",
            "The organizer's arrival is confirmed and the room is ready for the meeting.",
            "Checked in",
            "green",
        ),
    }
    heading, intro, status, tone = events.get(
        notification.event_type, ("Meeting update", "See the latest meeting details below.", "Update", "navy")
    )
    # Confirmation/change jobs may be delivered after a check-in. Show the real state.
    if notification.event_type in {"confirmation", "change"} and booking.status in {
        Reservation.Status.CHECKED_IN,
        Reservation.Status.COMPLETED,
    }:
        status = booking.get_status_display()
    start = timezone.localtime(booking.starts_at)
    end = timezone.localtime(booking.ends_at)
    organizer = booking.organizer.get_full_name().strip()
    organizer_label = f"{organizer} · {booking.organizer.email}" if organizer else booking.organizer.email
    metadata = [
        {"label": "Meeting", "value": booking.title},
        {"label": "Date", "value": start.strftime("%A, %d %B %Y")},
        {"label": "Time", "value": f"{start:%H:%M} – {end:%H:%M} Nepal time"},
        {
            "label": "Room",
            "value": f"{booking.room.name} · {booking.room.location}, Floor {booking.room.floor}",
        },
        {"label": "Organizer", "value": organizer_label},
        {"label": "Meeting type", "value": booking.get_meeting_type_display()},
    ]
    if booking.department:
        metadata.append({"label": "Department", "value": booking.department})
    if booking.guest_company_name:
        metadata.append({"label": "Guest company", "value": booking.guest_company_name})
    if booking.approved_at and booking.status in {
        Reservation.Status.APPROVED,
        Reservation.Status.CHECKED_IN,
        Reservation.Status.COMPLETED,
    }:
        # No invented human reviewer for rooms configured for automatic approval.
        metadata.append(
            {"label": "Approval", "value": "Staff approved" if booking.approved_by_id else "Automatic"}
        )
    paragraphs = []
    if booking.description:
        paragraphs.append(f"Purpose: {booking.description}")
    if notification.event_type == "rejection" and booking.rejection_reason:
        paragraphs.append(f"Reason: {booking.rejection_reason}")
    elif notification.event_type == "cancellation" and booking.cancellation_reason:
        paragraphs.append(f"Reason: {booking.cancellation_reason}")
    is_organizer = notification.recipient_email.casefold() == booking.organizer.email.casefold()
    notice = ""
    if not is_organizer and notification.event_type in {"confirmation", "change", "reminder"}:
        if can_view_meeting:
            notice = "You can see this meeting when you sign in with this company email. The organizer manages booking changes and check-in."
        else:
            notice = "The organizer manages booking changes and check-in. Contact the organizer for meeting details or updates."
    window = deadline_notice = ""
    if checkin_url:
        policy = BookingPolicy.objects.get(pk=1)
        deadline = start + timedelta(minutes=policy.check_in_minutes)
        window = f"Check in on {start:%d %B} between {start:%H:%M} and {deadline:%H:%M} Nepal time."
        deadline_notice = (
            f"If you do not check in by {deadline:%H:%M}, the booking is marked No show "
            "and the room is released."
        )
    return render_email(
        heading=heading,
        intro=intro,
        status=status,
        tone=tone,
        preheader=f"{booking.title} · {start:%d %b, %H:%M} · {booking.room.name}",
        metadata=metadata,
        paragraphs=paragraphs,
        action_url=public_url("booking-detail", booking.pk)
        if can_view_meeting
        else f"mailto:{booking.organizer.email}",
        action_label="View meeting" if can_view_meeting else "Contact organizer",
        checkin_url=checkin_url,
        checkin_window=window,
        checkin_notice=deadline_notice,
        notice=notice,
    )


@transaction.atomic
def _delivery_content(notification):
    if not Notification.objects.filter(
        pk=notification.pk, lease_token=notification.lease_token, status=Notification.Status.SENDING
    ).exists():
        return None
    if notification.reservation_id is None:
        html = render_email(
            heading="Let's find another meeting space.",
            intro="That room or time is unavailable. Choose another option to continue with your booking.",
            status="Time unavailable",
            tone="amber",
            paragraphs=[notification.body],
            action_url=public_url("booking-new"),
            action_label="Find a room",
        )
        return notification.body, html
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
    if (
        notification.event_type in {"reminder", "confirmation", "change"}
        and notification.reservation_revision is None
        and notification.created_at < booking.updated_at
    ):
        return None
    body = notification.body
    if notification.event_type == "reminder":
        policy = BookingPolicy.objects.get(pk=1)
        if (
            booking.status != Reservation.Status.APPROVED
            or notification.body != f"start={booking.starts_at.isoformat()}"
            or timezone.now() >= booking.starts_at + timedelta(minutes=policy.check_in_minutes)
        ):
            return None
        body = (
            f"Meeting '{booking.title}' starts on {timezone.localtime(booking.starts_at):%A %d %B %Y, %H:%M} Nepal time "
            f"in {booking.room.name}.\n\nView meeting: {public_url('booking-detail', booking.pk)}"
        )
    checkin_url = ""
    can_view_meeting = _recipient_can_view_meeting(booking, notification.recipient_email)
    if notification.event_type in {"reminder", "confirmation", "change"}:
        if can_view_meeting and notification.recipient_email.casefold() == booking.organizer.email.casefold():
            checkin_url = _checkin_link(booking)
            body += _checkin_instructions(booking, url=checkin_url)
        elif notification.event_type == "reminder":
            body += "\n\nThe organizer will receive a secure check-in link."
    if not can_view_meeting:
        body = body.replace(
            f"View meeting: {public_url('booking-detail', booking.pk)}",
            f"Contact organizer: {booking.organizer.email}",
        )
        body += "\n\nThe organizer manages booking changes and check-in. Contact the organizer for meeting details or updates."
    return body, _booking_email_html(notification, booking, checkin_url, can_view_meeting=can_view_meeting)


def _delivery_body(notification):
    """Keep the plain-text helper available without issuing a second check-in link."""
    content = _delivery_content(notification)
    return content[0] if content is not None else None


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
            content = _delivery_content(notification)
            if content is not None:
                body, html = content
                deliver_mail(notification.subject, body, [notification.recipient_email], html_body=html)
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
