"""Project approved room bookings into durable, per-recipient calendar messages."""

import hashlib
import json
from datetime import datetime
from email.utils import parseaddr

from django.conf import settings
from django.core.validators import validate_email
from django.db import transaction
from django.utils import timezone

from booking.models import CalendarEvent, CalendarInvitation, Notification, Reservation
from booking.services.calendar_invites import render_calendar_invite
from booking.services.email_templates import public_url, render_email
from booking.services.mail_delivery import safe_subject

CALENDAR_EVENTS = {"confirmation", "change", "request", "rejection", "cancellation", "no_show"}
CONFIRMED_STATUSES = {
    Reservation.Status.APPROVED,
    Reservation.Status.CHECKED_IN,
    Reservation.Status.COMPLETED,
}


def _snapshot(booking):
    return {
        "title": booking.title,
        "description": booking.description,
        "starts_at": booking.starts_at.isoformat(),
        "ends_at": booking.ends_at.isoformat(),
        "room_name": booking.room.name,
        "location": booking.room.location,
        "floor": booking.room.floor,
        "meeting_url": public_url("booking-detail", booking.pk),
        "booking_organizer_email": booking.organizer.email,
        "updated_at": booking.updated_at.isoformat(),
        "created_at": booking.created_at.isoformat(),
    }


@transaction.atomic
def project_calendar_invitations(booking, event_type):
    """Called by the transactional booking outbox; never backfill or broadcast."""
    if event_type not in CALENDAR_EVENTS or booking.kind != Reservation.Kind.BOOKING:
        return {}
    # The delivery worker takes this same lock through its bounded SMTP send.
    booking = (
        Reservation.objects.select_for_update(of=("self",))
        .select_related("room", "organizer")
        .get(pk=booking.pk)
    )
    event = CalendarEvent.objects.filter(reservation=booking).first()
    confirmed = booking.status in CONFIRMED_STATUSES
    if event is None:
        if not confirmed:
            return {}
        organizer_email = parseaddr(settings.DEFAULT_FROM_EMAIL)[1].strip().casefold()
        validate_email(organizer_email)
        event = CalendarEvent.objects.create(reservation=booking, organizer_email=organizer_email)
    snapshot = _snapshot(booking)
    participants = {booking.organizer.email.strip().casefold()}
    participants.update(
        email.strip().casefold() for email in booking.attendees.values_list("email", flat=True)
    )
    fingerprint = hashlib.sha256(
        json.dumps(
            {"status": booking.status, "snapshot": snapshot, "participants": sorted(participants)},
            sort_keys=True,
        ).encode()
    ).hexdigest()
    if fingerprint != event.fingerprint:
        event.sequence += 1
        event.fingerprint = fingerprint
        event.save(update_fields=["sequence", "fingerprint"])
        existing = {item.recipient_email: item for item in event.invitations.all()}
        if confirmed:
            for email in sorted(participants):
                item = existing.get(email)
                if item is None:
                    item = CalendarInvitation(event=event, recipient_email=email)
                item.method = CalendarInvitation.Method.REQUEST
                item.sequence = event.sequence
                item.snapshot = snapshot
                item.save()
                existing[email] = item
        for email, item in existing.items():
            if confirmed and email in participants or item.method == CalendarInvitation.Method.CANCEL:
                continue
            # Keep their last approved details: a removed attendee must not learn
            # the new title, description, room or organizer through a CANCEL.
            item.method = CalendarInvitation.Method.CANCEL
            item.sequence = event.sequence
            item.snapshot = {**item.snapshot, "updated_at": booking.updated_at.isoformat()}
            item.save(update_fields=["method", "sequence", "snapshot"])
    outstanding = {}
    for item in event.invitations.all():
        if (
            item.sent_sequence == item.sequence
            or Notification.objects.filter(
                calendar_invitation=item,
                calendar_sequence=item.sequence,
                status__in=[
                    Notification.Status.PENDING,
                    Notification.Status.FAILED,
                    Notification.Status.SENDING,
                ],
            ).exists()
        ):
            continue
        outstanding[item.recipient_email] = item
    return outstanding


def queue_unmatched_calendar_notifications(booking, invitations):
    """Former attendees also need cancellations after losing application access."""
    for email, invitation in invitations.items():
        if Notification.objects.filter(
            calendar_invitation=invitation,
            calendar_sequence=invitation.sequence,
            status__in=[Notification.Status.PENDING, Notification.Status.FAILED, Notification.Status.SENDING],
        ).exists():
            continue
        Notification.objects.create(
            reservation=booking,
            reservation_revision=booking.revision,
            recipient_email=email,
            recipient_role=Notification.RecipientRole.PARTICIPANT,
            calendar_invitation=invitation,
            calendar_sequence=invitation.sequence,
            event_type="calendar",
            subject=safe_subject(
                f"Calendar {'cancellation' if invitation.method == 'CANCEL' else 'invitation'}: {invitation.snapshot['title']}"
            ),
            body="Calendar notice",
            next_attempt_at=timezone.now(),
        )


def current_calendar_invitation(notification, booking):
    if not notification.calendar_invitation_id:
        return None
    invitation = CalendarInvitation.objects.select_related("event").get(
        pk=notification.calendar_invitation_id
    )
    if (
        invitation.event.reservation_id != booking.pk
        or invitation.recipient_email != notification.recipient_email.casefold()
        or invitation.sequence != notification.calendar_sequence
        or invitation.sent_sequence == invitation.sequence
    ):
        return None
    if invitation.method == CalendarInvitation.Method.REQUEST:
        participant = (
            invitation.recipient_email == booking.organizer.email.casefold()
            or booking.attendees.filter(email__iexact=invitation.recipient_email).exists()
        )
        if booking.status not in CONFIRMED_STATUSES or not participant or timezone.now() >= booking.ends_at:
            return None
    return invitation


def calendar_cancellation_content(invitation, booking):
    snapshot = invitation.snapshot
    pending = booking.status == Reservation.Status.PENDING
    current_participant = (
        invitation.recipient_email == booking.organizer.email.casefold()
        or booking.attendees.filter(email__iexact=invitation.recipient_email).exists()
    )
    intro = "The previous calendar invitation has been withdrawn."
    if pending:
        intro += " The revised booking is awaiting Front Desk approval. A new invitation will follow if it is approved."
    else:
        intro += " This reservation no longer applies to you."
    if current_participant and booking.status == Reservation.Status.NO_SHOW:
        intro += " The booking is marked No show because the organizer did not check in before the deadline."
    start = timezone.localtime(datetime.fromisoformat(snapshot["starts_at"]))
    end = timezone.localtime(datetime.fromisoformat(snapshot["ends_at"]))
    body = (
        f"{intro}\n\nMeeting: {snapshot['title']}\nRoom: {snapshot['room_name']}\n"
        f"Date: {start:%A, %d %B %Y}\nTime: {start:%H:%M} – {end:%H:%M} Nepal time\n\n"
        "Process this cancellation in your calendar to remove the previous meeting. "
        "Calendar responses do not change the booking in MBS."
    )
    html = render_email(
        heading="Your calendar has an update.",
        intro=intro,
        status="Invitation cancelled",
        tone="red",
        metadata=[
            {"label": "Meeting", "value": snapshot["title"]},
            {"label": "Room", "value": snapshot["room_name"]},
            {"label": "Date", "value": start.strftime("%A, %d %B %Y")},
            {"label": "Time", "value": f"{start:%H:%M} – {end:%H:%M} Nepal time"},
        ],
        notice="Process the attached cancellation in your calendar. Calendar responses do not change the booking in MBS.",
    )
    return body, html


def calendar_mail_options(invitation):
    uid = f"{invitation.event.uid}@meeting-rooms"
    recipient_key = hashlib.sha256(invitation.recipient_email.encode()).hexdigest()[:24]
    return {
        "calendar_body": render_calendar_invite(
            invitation.snapshot,
            uid=uid,
            sequence=invitation.sequence,
            method=invitation.method,
            organizer_email=invitation.event.organizer_email,
            recipient_email=invitation.recipient_email,
        ),
        "calendar_method": invitation.method,
        "from_email": invitation.event.organizer_email,
        "message_id": f"<{invitation.event.uid}.{invitation.sequence}.{recipient_key}@meeting-rooms>",
    }
