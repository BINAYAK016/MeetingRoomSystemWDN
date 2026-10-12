"""End-to-end scheduling mail regressions; all delivery stays in locmem."""

from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from datetime import timezone as datetime_timezone
from queue import Queue
from threading import Event
from time import monotonic
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.core.mail import EmailMultiAlternatives
from django.db import close_old_connections, connection, connections
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from icalendar import Calendar

from booking.management.commands.retry_failed_mail import retry_failed_mail
from booking.models import (
    BookingPolicy,
    CalendarEvent,
    CalendarInvitation,
    Department,
    Notification,
    Reservation,
    Room,
    User,
)
from booking.services.bookings import (
    approve_booking,
    cancel_booking,
    create_booking,
    reject_booking,
    update_booking,
)
from booking.services.checkin import complete_finished, manual_checkin, release_due_no_shows
from booking.services.notifications import queue_due_reminders, send_due_notifications

NEPAL = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 5, 8, tzinfo=NEPAL)
DAY = date(2026, 10, 6)
SERVICE_EMAIL = "mbs@wdn.com.np"


def calendar_parts(message):
    return [part for part in message.message().walk() if part.get_content_type() == "text/calendar"]


def decoded_text(message):
    return "\n".join(
        part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
        for part in message.message().walk()
        if part.get_content_maintype() == "text"
    )


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_READY=True,
    DEFAULT_FROM_EMAIL=SERVICE_EMAIL,
    PUBLIC_BASE_URL="http://mbs.example.test",
    BOOKING_FRONT_DESK_EMAIL="mijala.maharjan@wdn.com.np",
)
class CalendarInvitationWorkflowTests(TestCase):
    def setUp(self):
        Department.objects.get_or_create(name="Operations")
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.organizer = User.objects.create_user("organizer@wdn.com.np", first_name="Binayak")
        self.front_desk = User.objects.create_user("mijala.maharjan@wdn.com.np", is_staff=True)
        self.other_staff = User.objects.create_user("other.staff@transgate.com.np", is_staff=True)
        self.room = Room.objects.create(
            name="Meeting room – काठमाडौं",
            location="Kantipath",
            floor="3",
            capacity=12,
            requires_approval=False,
        )
        self.reviewed_room = Room.objects.create(
            name="Reviewed room",
            location="Kantipath",
            floor="2",
            capacity=12,
            requires_approval=True,
        )
        self.participants = {
            self.organizer.email,
            "attendee@wdn.com.np",
            "colleague@transgate.com.np",
            "guest@outside.example",
        }

    def values(self, room=None, **changes):
        values = {
            "room": room or self.room,
            "date": DAY,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Quarterly planning – योजना, budget; decisions",
            "description": "Discuss café launch, budget; and plans.\nSecond line: नमस्ते.",
            "meeting_type": Reservation.MeetingType.EXTERNAL,
            "guest_company_name": "Partner Company",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": sorted(self.participants - {self.organizer.email}),
            "refreshments_requested": False,
            "front_desk_notes": "Private desk instructions: never include in the calendar",
            "recurrence": "none",
            "until_date": None,
        }
        values.update(changes)
        return values

    def created(self, room=None, **changes):
        return create_booking(self.values(room, **changes), actor=self.organizer)[0]

    def approve(self, booking):
        request = RequestFactory().post("/staff/")
        request.user = self.front_desk
        request.session = {"staff_verified": True, "staff_auth_version": self.front_desk.auth_version}
        return approve_booking(booking.pk, actor=self.front_desk, request=request)

    def drain(self):
        send_due_notifications(limit=100)
        messages = list(mail.outbox)
        mail.outbox.clear()
        return messages

    def by_recipient(self, messages):
        return {message.to[0]: message for message in messages}

    def scheduling(self, message, method="REQUEST"):
        parts = calendar_parts(message)
        self.assertEqual(len(parts), 1, "One scheduling part belongs on the existing booking email")
        part = parts[0]
        self.assertEqual(part.get_param("method"), method)
        self.assertEqual(part.get_filename(), "invitation.ics")
        calendar = Calendar.from_ical(part.get_payload(decode=True))
        self.assertEqual(str(calendar["METHOD"]), method)
        events = calendar.walk("VEVENT")
        self.assertEqual(len(events), 1)
        return calendar, events[0]

    def test_confirmed_booking_invites_organizer_and_company_and_external_attendees_only(self):
        booking = self.created()
        messages = self.by_recipient(self.drain())
        self.assertSetEqual(set(messages), self.participants | {self.front_desk.email})
        self.assertNotIn(self.other_staff.email, messages)
        self.assertEqual(len(messages), 5, "Invitations must not duplicate confirmation emails")
        uids = set()
        for email in self.participants:
            message = messages[email]
            _, event = self.scheduling(message)
            uids.add(str(event["UID"]))
            self.assertEqual(str(event["SUMMARY"]), booking.title)
            self.assertIn(booking.description, str(event["DESCRIPTION"]))
            self.assertEqual(str(event["ORGANIZER"]).casefold(), "mailto:" + SERVICE_EMAIL)
            attendees = event.get("ATTENDEE", [])
            if not isinstance(attendees, list):
                attendees = [attendees]
            self.assertEqual([str(value).casefold() for value in attendees], ["mailto:" + email])
            self.assertEqual(
                event.decoded("DTSTART"), datetime(2026, 10, 6, 5, 15, tzinfo=datetime_timezone.utc)
            )
            self.assertEqual(
                event.decoded("DTEND"), datetime(2026, 10, 6, 6, 15, tzinfo=datetime_timezone.utc)
            )
            self.assertIn(self.room.name, str(event["LOCATION"]))
            self.assertNotIn("/check-in/", calendar_parts(message)[0].get_payload(decode=True).decode())
            self.assertNotIn(
                "Private desk instructions", calendar_parts(message)[0].get_payload(decode=True).decode()
            )
        self.assertEqual(len(uids), 1)
        self.assertEqual(calendar_parts(messages[self.front_desk.email]), [])
        self.assertEqual(CalendarEvent.objects.filter(reservation=booking).count(), 1)
        self.assertEqual(CalendarInvitation.objects.filter(event__reservation=booking).count(), 4)

    def test_calendar_mime_keeps_readable_alternatives_and_inline_logo(self):
        self.created()
        message = self.by_recipient(self.drain())[self.organizer.email]
        mime = message.message()
        self.assertEqual(mime.get_content_type(), "multipart/alternative")
        self.assertEqual(
            [part.get_content_type() for part in mime.get_payload()],
            ["text/plain", "multipart/related", "text/calendar"],
        )
        related = mime.get_payload()[1]
        self.assertEqual(related.get_payload()[0].get_content_type(), "text/html")
        images = [part for part in related.walk() if part.get_content_type() == "image/png"]
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].get_content_disposition(), "inline")
        self.assertIn("Check in", decoded_text(message))

    def test_pending_request_and_rejection_do_not_send_calendar_invitations(self):
        booking = self.created(self.reviewed_room)
        messages = self.drain()
        self.assertEqual(len(messages), 2)
        self.assertTrue(all(not calendar_parts(message) for message in messages))
        self.assertFalse(CalendarInvitation.objects.filter(event__reservation=booking).exists())
        request = RequestFactory().post("/staff/")
        request.user = self.front_desk
        request.session = {"staff_verified": True, "staff_auth_version": self.front_desk.auth_version}
        reject_booking(booking.pk, actor=self.front_desk, request=request, reason="Room reserved")
        self.assertTrue(all(not calendar_parts(message) for message in self.drain()))

    def test_staff_approval_creates_first_invitation_and_noop_edit_creates_nothing(self):
        booking = self.created(self.reviewed_room)
        self.drain()
        booking = self.approve(booking)
        messages = self.by_recipient(self.drain())
        self.assertSetEqual(
            {email for email, message in messages.items() if calendar_parts(message)}, self.participants
        )
        first_event = self.scheduling(messages[self.organizer.email])[1]
        update_booking(booking.pk, self.values(self.reviewed_room), actor=self.organizer)
        self.assertEqual(self.drain(), [])
        self.assertEqual(
            CalendarEvent.objects.get(reservation=booking).sequence, int(first_event["SEQUENCE"])
        )

    def test_approved_edit_updates_same_uid_and_service_organizer_survives_sender_change(self):
        booking = self.created()
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        with override_settings(DEFAULT_FROM_EMAIL="new-service@wdn.com.np"):
            booking = update_booking(
                booking.pk,
                self.values(title="Revised planning", start_time=time(13), end_time=time(14)),
                actor=self.organizer,
            )
            messages = self.by_recipient(self.drain())
        for email in self.participants:
            event = self.scheduling(messages[email])[1]
            self.assertEqual(str(event["UID"]), str(initial["UID"]))
            self.assertGreater(int(event["SEQUENCE"]), int(initial["SEQUENCE"]))
            self.assertEqual(str(event["SUMMARY"]), "Revised planning")
            self.assertEqual(str(event["ORGANIZER"]).casefold(), "mailto:" + SERVICE_EMAIL)
        self.assertEqual(CalendarEvent.objects.get(reservation=booking).organizer_email, SERVICE_EMAIL)

    def test_removed_attendee_and_former_organizer_cancel_only_the_previous_snapshot(self):
        booking = self.created()
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        new_organizer = User.objects.create_user("new.organizer@transgate.com.np")
        new_attendee = "new.attendee@wdn.com.np"
        old_title, old_description = booking.title, booking.description
        update_booking(
            booking.pk,
            self.values(
                organizer_email=new_organizer.email,
                attendees=[new_attendee],
                title="Confidential new title",
                description="Confidential new plan",
                start_time=time(13),
                end_time=time(14),
            ),
            actor=self.front_desk,
            staff=True,
        )
        messages = self.by_recipient(self.drain())
        for email in self.participants:
            event = self.scheduling(messages[email], "CANCEL")[1]
            self.assertEqual(str(event["UID"]), str(initial["UID"]))
            self.assertGreater(int(event["SEQUENCE"]), int(initial["SEQUENCE"]))
            self.assertEqual(str(event["SUMMARY"]), old_title)
            self.assertIn(old_description, str(event["DESCRIPTION"]))
            text = decoded_text(messages[email])
            self.assertNotIn("Confidential new title", messages[email].subject)
            for private in (
                "Confidential new title",
                "Confidential new plan",
                new_attendee,
                "Private desk instructions",
            ):
                self.assertNotIn(private, text)
            self.assertNotIn("/check-in/", text)
        for email in (new_organizer.email, new_attendee):
            event = self.scheduling(messages[email])[1]
            self.assertEqual(str(event["UID"]), str(initial["UID"]))
            self.assertEqual(str(event["SUMMARY"]), "Confidential new title")
        self.assertFalse(calendar_parts(messages[self.front_desk.email]))

    def test_employee_edit_revokes_approval_cancels_old_invites_and_reapproval_uses_same_uid(self):
        booking = self.created()
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        booking = update_booking(
            booking.pk,
            self.values(self.reviewed_room, title="Needs review now"),
            actor=self.organizer,
        )
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        messages = self.by_recipient(self.drain())
        for email in self.participants:
            cancelled = self.scheduling(messages[email], "CANCEL")[1]
            self.assertEqual(str(cancelled["UID"]), str(initial["UID"]))
            self.assertGreater(int(cancelled["SEQUENCE"]), int(initial["SEQUENCE"]))
            self.assertNotIn(
                "Needs review now", calendar_parts(messages[email])[0].get_payload(decode=True).decode()
            )
        cancelled_sequence = int(cancelled["SEQUENCE"])
        self.approve(booking)
        messages = self.by_recipient(self.drain())
        for email in self.participants:
            event = self.scheduling(messages[email])[1]
            self.assertEqual(str(event["UID"]), str(initial["UID"]))
            self.assertGreater(int(event["SEQUENCE"]), cancelled_sequence)
            self.assertEqual(str(event["SUMMARY"]), "Needs review now")

    def test_staff_edit_retains_approval_and_sends_update_in_reviewed_room(self):
        booking = self.created(self.reviewed_room)
        self.approve(booking)
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        updated = update_booking(
            booking.pk,
            self.values(
                self.reviewed_room,
                title="Staff corrected title",
                organizer_email=self.organizer.email,
            ),
            actor=self.front_desk,
            staff=True,
        )
        self.assertEqual(updated.status, Reservation.Status.APPROVED)
        event = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        self.assertEqual(str(event["UID"]), str(initial["UID"]))
        self.assertGreater(int(event["SEQUENCE"]), int(initial["SEQUENCE"]))

    def test_cancellation_and_no_show_cancel_existing_calendar_events(self):
        booking = self.created()
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        cancel_booking(booking.pk, actor=self.organizer)
        messages = self.by_recipient(self.drain())
        for email in self.participants:
            event = self.scheduling(messages[email], "CANCEL")[1]
            self.assertEqual(str(event["UID"]), str(initial["UID"]))
            self.assertEqual(str(event["STATUS"]), "CANCELLED")
        second = self.created(start_time=time(13), end_time=time(14))
        second_initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        with patch("django.utils.timezone.now", return_value=second.starts_at + timedelta(minutes=15)):
            self.assertEqual(release_due_no_shows(), 1)
            messages = self.by_recipient(self.drain())
        for email in self.participants:
            event = self.scheduling(messages[email], "CANCEL")[1]
            self.assertEqual(str(event["UID"]), str(second_initial["UID"]))

    def test_reminder_and_checkin_email_have_no_calendar_invitation_or_duplicate_event(self):
        booking = self.created()
        self.drain()
        sequence = CalendarEvent.objects.get(reservation=booking).sequence
        with patch("django.utils.timezone.now", return_value=booking.starts_at - timedelta(minutes=30)):
            self.assertGreater(queue_due_reminders(), 0)
            reminders = self.drain()
        self.assertTrue(all(not calendar_parts(message) for message in reminders))
        organizer_mail = self.by_recipient(reminders)[self.organizer.email]
        self.assertIn("/check-in/link/", decoded_text(organizer_mail))
        with patch("django.utils.timezone.now", return_value=booking.starts_at):
            manual_checkin(booking.pk, actor=self.front_desk)
            self.assertTrue(all(not calendar_parts(message) for message in self.drain()))
        self.assertEqual(CalendarEvent.objects.get(reservation=booking).sequence, sequence)

    def test_recurring_occurrences_are_independent_events_within_the_booking_window(self):
        bookings = create_booking(
            self.values(recurrence="daily", until_date=DAY + timedelta(days=2)),
            actor=self.organizer,
        )
        messages = self.drain()
        events = [self.scheduling(message)[1] for message in messages if message.to == [self.organizer.email]]
        self.assertEqual(len(events), 3)
        self.assertEqual(len({str(event["UID"]) for event in events}), 3)
        self.assertTrue(all("RRULE" not in event for event in events))
        self.assertEqual(
            {event.decoded("DTSTART").astimezone(NEPAL).date() for event in events},
            {booking.starts_at.date() for booking in bookings},
        )

    def test_retry_reuses_calendar_payload_and_marks_sent_sequence_only_after_success(self):
        booking = self.created(attendees=[])
        captured = []
        original_send = EmailMultiAlternatives.send

        def fail_once(message, *args, **kwargs):
            parts = calendar_parts(message)
            if parts:
                captured.append(parts[0].get_payload(decode=True))
                if len(captured) == 1:
                    raise OSError("temporary transport error")
            return original_send(message, *args, **kwargs)

        with patch.object(EmailMultiAlternatives, "send", fail_once):
            send_due_notifications(limit=100)
            failed = Notification.objects.get(reservation=booking, status=Notification.Status.FAILED)
            invitation = CalendarInvitation.objects.get(
                event__reservation=booking, recipient_email=self.organizer.email
            )
            self.assertIsNone(invitation.sent_sequence)
            with patch(
                "django.utils.timezone.now", return_value=failed.next_attempt_at + timedelta(seconds=1)
            ):
                send_due_notifications(limit=100)
        self.assertEqual(len(captured), 2)
        self.assertEqual(captured[0], captured[1])
        invitation.refresh_from_db()
        self.assertEqual(invitation.sent_sequence, invitation.sequence)
        failed.refresh_from_db()
        self.assertEqual(failed.status, Notification.Status.SENT)
        self.assertEqual(failed.attempts, 2)

    def test_unsent_previous_revision_is_skipped_and_only_latest_calendar_details_are_delivered(self):
        booking = self.created()
        previous = list(Notification.objects.filter(reservation=booking).values_list("pk", flat=True))
        update_booking(booking.pk, self.values(title="Latest approved details"), actor=self.organizer)
        messages = self.by_recipient(self.drain())
        self.assertEqual(
            Notification.objects.filter(pk__in=previous, status=Notification.Status.SKIPPED).count(),
            len(previous),
        )
        self.assertEqual(len(messages), 5)
        for email in self.participants:
            event = self.scheduling(messages[email])[1]
            self.assertEqual(str(event["SUMMARY"]), "Latest approved details")

    def test_front_desk_receives_invitation_only_when_explicitly_participating(self):
        self.created(attendees=[self.front_desk.email])
        messages = self.by_recipient(self.drain())
        self.assertSetEqual(set(messages), {self.organizer.email, self.front_desk.email})
        self.scheduling(messages[self.front_desk.email])

    def test_failed_request_is_superseded_by_cancellation_with_higher_sequence(self):
        booking = self.created(attendees=[])
        failed_requests = []
        original_send = EmailMultiAlternatives.send

        def fail_request(message, *args, **kwargs):
            parts = calendar_parts(message)
            if parts and parts[0].get_param("method") == "REQUEST":
                failed_requests.append(
                    Calendar.from_ical(parts[0].get_payload(decode=True)).walk("VEVENT")[0]
                )
                raise OSError("Ambiguous SMTP result; relay may have accepted the invitation")
            return original_send(message, *args, **kwargs)

        with patch.object(EmailMultiAlternatives, "send", fail_request):
            send_due_notifications(limit=100)
        self.assertEqual(len(failed_requests), 1)
        failed = Notification.objects.get(reservation=booking, status=Notification.Status.FAILED)
        mail.outbox.clear()
        cancel_booking(booking.pk, actor=self.organizer)
        failed.refresh_from_db()
        self.assertEqual(failed.status, Notification.Status.SKIPPED)
        messages = self.by_recipient(self.drain())
        cancellation = self.scheduling(messages[self.organizer.email], "CANCEL")[1]
        self.assertEqual(str(cancellation["UID"]), str(failed_requests[0]["UID"]))
        self.assertGreater(int(cancellation["SEQUENCE"]), int(failed_requests[0]["SEQUENCE"]))
        self.assertEqual(retry_failed_mail(failed.pk), (0, 0))

    def test_failed_removed_attendee_cancellation_can_be_requeued_after_meeting_end(self):
        booking = self.created(attendees=["removed@transgate.com.np"])
        self.drain()
        update_booking(
            booking.pk, self.values(attendees=[], title="Private latest meeting"), actor=self.organizer
        )
        cancellation = Notification.objects.get(
            reservation=booking,
            recipient_email="removed@transgate.com.np",
            calendar_invitation__method="CANCEL",
            status=Notification.Status.PENDING,
        )
        Notification.objects.filter(pk=cancellation.pk).update(status=Notification.Status.FAILED, attempts=5)
        with patch("django.utils.timezone.now", return_value=booking.ends_at + timedelta(days=1)):
            self.assertEqual(retry_failed_mail(cancellation.pk), (1, 0))
            messages = self.by_recipient(self.drain())
        message = messages["removed@transgate.com.np"]
        self.scheduling(message, "CANCEL")
        self.assertNotIn("Private latest meeting", message.subject + decoded_text(message))

    def test_failed_approval_revocation_cancellation_can_be_requeued_after_request_expiry(self):
        booking = self.created(attendees=[])
        self.drain()
        update_booking(booking.pk, self.values(self.reviewed_room, attendees=[]), actor=self.organizer)
        cancellation = Notification.objects.get(
            reservation=booking,
            recipient_email=self.organizer.email,
            calendar_invitation__method="CANCEL",
            status=Notification.Status.PENDING,
        )
        Notification.objects.filter(pk=cancellation.pk).update(status=Notification.Status.FAILED, attempts=5)
        with patch("django.utils.timezone.now", return_value=booking.ends_at + timedelta(days=1)):
            self.assertEqual(retry_failed_mail(cancellation.pk), (1, 0))
            messages = self.by_recipient(self.drain())
        self.scheduling(messages[self.organizer.email], "CANCEL")

    def test_expired_cancellation_lease_is_reclaimed_without_changing_calendar_identity(self):
        booking = self.created(attendees=[])
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        cancel_booking(booking.pk, actor=self.organizer)
        cancellation = Notification.objects.get(
            reservation=booking,
            recipient_email=self.organizer.email,
            calendar_invitation__method="CANCEL",
            status=Notification.Status.PENDING,
        )
        Notification.objects.filter(pk=cancellation.pk).update(
            status=Notification.Status.SENDING,
            attempts=1,
            lease_expires_at=NOW - timedelta(seconds=1),
        )
        messages = self.by_recipient(self.drain())
        event = self.scheduling(messages[self.organizer.email], "CANCEL")[1]
        self.assertEqual(str(event["UID"]), str(initial["UID"]))
        self.assertEqual(int(event["SEQUENCE"]), cancellation.calendar_sequence)
        cancellation.refresh_from_db()
        self.assertEqual(cancellation.status, Notification.Status.SENT)
        self.assertEqual(cancellation.attempts, 2)

    def test_pending_calendar_request_is_skipped_at_meeting_end(self):
        booking = self.created(attendees=[])
        invitation_job = Notification.objects.get(
            reservation=booking,
            recipient_email=self.organizer.email,
        )
        with patch("django.utils.timezone.now", return_value=booking.ends_at):
            messages = self.drain()
        self.assertTrue(all(not calendar_parts(message) for message in messages))
        invitation_job.refresh_from_db()
        self.assertEqual(invitation_job.status, Notification.Status.SKIPPED)
        self.assertIsNone(CalendarInvitation.objects.get(event__reservation=booking).sent_sequence)

    def test_failed_calendar_request_is_skipped_after_checked_in_meeting_completes(self):
        booking = self.created(attendees=[])
        original_send = EmailMultiAlternatives.send

        def fail_invitation(message, *args, **kwargs):
            if calendar_parts(message):
                raise OSError("Calendar relay unavailable")
            return original_send(message, *args, **kwargs)

        with patch.object(EmailMultiAlternatives, "send", fail_invitation):
            self.drain()
        invitation_job = Notification.objects.get(reservation=booking, status=Notification.Status.FAILED)
        with patch("django.utils.timezone.now", return_value=booking.starts_at):
            manual_checkin(booking.pk, actor=self.front_desk)
        with patch("django.utils.timezone.now", return_value=booking.ends_at + timedelta(seconds=1)):
            self.assertEqual(complete_finished(), 1)
            messages = self.drain()
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.COMPLETED)
        self.assertTrue(all(not calendar_parts(message) for message in messages))
        invitation_job.refresh_from_db()
        self.assertEqual(invitation_job.status, Notification.Status.SKIPPED)
        self.assertIsNone(CalendarInvitation.objects.get(event__reservation=booking).sent_sequence)

    def test_organizer_and_participating_front_desk_keep_actionable_revised_request_with_old_cancel(self):
        booking = self.created(attendees=[self.front_desk.email])
        initial = self.scheduling(self.by_recipient(self.drain())[self.organizer.email])[1]
        revised = update_booking(
            booking.pk,
            self.values(
                self.reviewed_room,
                title="Updated request needs Front Desk review",
                attendees=[self.front_desk.email],
                start_time=time(13),
                end_time=time(14),
            ),
            actor=self.organizer,
        )
        self.assertEqual(revised.status, Reservation.Status.PENDING)
        messages = self.by_recipient(self.drain())
        self.assertSetEqual(set(messages), {self.organizer.email, self.front_desk.email})
        details_url = "http://mbs.example.test" + reverse("booking-detail", args=[booking.pk])
        for email in (self.organizer.email, self.front_desk.email):
            message = messages[email]
            self.assertIn(revised.title, message.subject)
            self.assertIn(revised.title, message.body)
            self.assertIn(details_url, message.body)
            self.assertIn("awaiting", message.body.casefold())
            html = next(
                part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8")
                for part in message.message().walk()
                if part.get_content_type() == "text/html"
            )
            self.assertIn(revised.title, html)
            self.assertIn("View meeting", html)
            self.assertIn(details_url, html)
            self.assertIn("Awaiting approval", html)
            cancelled = self.scheduling(message, "CANCEL")[1]
            self.assertEqual(str(cancelled["UID"]), str(initial["UID"]))
            self.assertEqual(str(cancelled["SUMMARY"]), str(initial["SUMMARY"]))
            self.assertEqual(cancelled.decoded("DTSTART"), initial.decoded("DTSTART"))
            self.assertEqual(cancelled.decoded("DTEND"), initial.decoded("DTEND"))
            self.assertNotIn(revised.title, calendar_parts(message)[0].get_payload(decode=True).decode())


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMAIL_READY=True,
    DEFAULT_FROM_EMAIL=SERVICE_EMAIL,
    PUBLIC_BASE_URL="http://mbs.example.test",
    BOOKING_FRONT_DESK_EMAIL="",
)
class CalendarDeliveryConcurrencyTests(TransactionTestCase):
    def setUp(self):
        BookingPolicy.objects.get_or_create(pk=1)
        Department.objects.get_or_create(name="Operations")
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.organizer = User.objects.create_user("race.organizer@wdn.com.np")
        self.room = Room.objects.create(
            name="Concurrency room",
            location="Kantipath",
            floor="3",
            capacity=8,
            requires_approval=False,
        )
        self.values = {
            "room": self.room,
            "date": DAY,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Original approved title",
            "description": "Original plan",
            "meeting_type": Reservation.MeetingType.INTERNAL,
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": [],
            "refreshments_requested": False,
            "front_desk_notes": "",
            "recurrence": "none",
            "until_date": None,
        }
        self.booking = create_booking(self.values, actor=self.organizer)[0]

    def test_calendar_smtp_finishes_before_concurrent_booking_edit_can_commit(self):
        if connection.vendor != "postgresql":
            self.skipTest("The production transaction serialization contract requires PostgreSQL")
        smtp_entered, release_smtp, edit_finished = Event(), Event(), Event()
        edit_pid = Queue()
        original_send = EmailMultiAlternatives.send

        def blocked_send(message, *args, **kwargs):
            smtp_entered.set()
            if not release_smtp.wait(timeout=15):
                raise TimeoutError("Test did not release the bounded SMTP operation")
            return original_send(message, *args, **kwargs)

        def deliver():
            close_old_connections()
            try:
                return send_due_notifications(limit=1)
            finally:
                connections.close_all()

        def edit():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_backend_pid()")
                    edit_pid.put(cursor.fetchone()[0])
                updated = update_booking(
                    self.booking.pk,
                    {**self.values, "title": "Concurrent revised title"},
                    actor=self.organizer,
                )
                edit_finished.set()
                return updated.pk
            finally:
                connections.close_all()

        with patch.object(EmailMultiAlternatives, "send", blocked_send):
            with ThreadPoolExecutor(max_workers=2) as pool:
                delivery = pool.submit(deliver)
                try:
                    self.assertTrue(smtp_entered.wait(timeout=10))
                    editing = pool.submit(edit)
                    pid = edit_pid.get(timeout=10)
                    waiting = False
                    deadline = monotonic() + 5
                    while monotonic() < deadline:
                        with connection.cursor() as cursor:
                            cursor.execute(
                                "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [pid]
                            )
                            state = cursor.fetchone()
                        if state and state[0] == "Lock":
                            waiting = True
                            break
                        if edit_finished.wait(timeout=0.02):
                            break
                    self.assertTrue(
                        waiting, "Concurrent booking edit must wait for calendar SMTP's reservation lock"
                    )
                    self.assertFalse(edit_finished.is_set())
                finally:
                    release_smtp.set()
                self.assertEqual(delivery.result(timeout=15), 1)
                self.assertEqual(editing.result(timeout=15), self.booking.pk)
        first_event = Calendar.from_ical(calendar_parts(mail.outbox[0])[0].get_payload(decode=True)).walk(
            "VEVENT"
        )[0]
        self.assertEqual(str(first_event["SUMMARY"]), "Original approved title")
        mail.outbox.clear()
        self.assertEqual(send_due_notifications(limit=10), 1)
        update_event = Calendar.from_ical(calendar_parts(mail.outbox[0])[0].get_payload(decode=True)).walk(
            "VEVENT"
        )[0]
        self.assertEqual(str(update_event["SUMMARY"]), "Concurrent revised title")
        self.assertEqual(str(update_event["UID"]), str(first_event["UID"]))
        self.assertGreater(int(update_event["SEQUENCE"]), int(first_event["SEQUENCE"]))
