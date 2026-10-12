from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import TestCase, override_settings
from django.utils import timezone

from booking.models import (
    BookingAttendee,
    BookingPolicy,
    CalendarEvent,
    CalendarInvitation,
    Notification,
    Reservation,
    Room,
    User,
)
from booking.services.notifications import queue_booking_event, queue_due_reminders, send_due_notifications


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    BOOKING_FRONT_DESK_EMAIL="mijala.maharjan@wdn.com.np",
)
class FrontDeskNotificationTests(TestCase):
    def setUp(self):
        self.now = timezone.now()
        clock = patch("django.utils.timezone.now", return_value=self.now)
        clock.start()
        self.addCleanup(clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.organizer = User.objects.create_user("organizer@wdn.com.np")
        self.attendee = User.objects.create_user("attendee@transgate.com.np")
        self.front_desk = User.objects.create_user("mijala.maharjan@wdn.com.np", is_staff=True)
        self.other_staff = User.objects.create_user("other.admin@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Meeting room", location="Office", floor="1", capacity=10)
        start = self.now + timedelta(minutes=30)
        self.booking = Reservation.objects.create(
            room=self.room,
            organizer=self.organizer,
            created_by=self.organizer,
            kind=Reservation.Kind.BOOKING,
            status=Reservation.Status.APPROVED,
            title="Office meeting",
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            occupied_from=start,
            occupied_until=start + timedelta(hours=1, minutes=15),
        )
        BookingAttendee.objects.create(reservation=self.booking, email=self.attendee.email)

    def recipients(self):
        return set(Notification.objects.values_list("recipient_email", flat=True))

    def test_all_booking_events_route_staff_copy_to_front_desk_only(self):
        states = {
            "request": Reservation.Status.PENDING,
            "confirmation": Reservation.Status.APPROVED,
            "change": Reservation.Status.APPROVED,
            "rejection": Reservation.Status.REJECTED,
            "cancellation": Reservation.Status.CANCELLED,
            "no_show": Reservation.Status.NO_SHOW,
            "check_in": Reservation.Status.CHECKED_IN,
        }
        for event, status in states.items():
            with self.subTest(event=event):
                Notification.objects.all().delete()
                # Each subtest is an independent event, not an approved meeting
                # being rejected after invitations have already been delivered.
                CalendarInvitation.objects.all().delete()
                CalendarEvent.objects.all().delete()
                mail.outbox.clear()
                self.booking.status = status
                self.booking.rejection_reason = "Choose another time"
                self.booking.rejected_at = self.now
                self.booking.save()
                queue_booking_event(self.booking, event)
                expected = {self.organizer.email, self.front_desk.email}
                if event not in {"request", "rejection"}:
                    expected.add(self.attendee.email)
                self.assertSetEqual(self.recipients(), expected)
                self.assertEqual(send_due_notifications(), len(expected))
                self.assertSetEqual({message.to[0] for message in mail.outbox}, expected)
                desk_mail = next(item for item in mail.outbox if item.to == [self.front_desk.email])
                self.assertNotIn("/check-in/link/", desk_mail.body)

    def test_reminders_only_include_front_desk_staff_copy_and_deduplicate(self):
        self.assertEqual(queue_due_reminders(), 3)
        self.assertEqual(queue_due_reminders(), 0)
        self.assertSetEqual(
            self.recipients(), {self.organizer.email, self.attendee.email, self.front_desk.email}
        )
        self.assertEqual(send_due_notifications(), 3)
        self.assertNotIn(self.other_staff.email, {message.to[0] for message in mail.outbox})

    def test_other_staff_still_receive_normal_organizer_or_attendee_notifications(self):
        self.booking.organizer = self.other_staff
        self.booking.save(update_fields=["organizer"])
        BookingAttendee.objects.create(reservation=self.booking, email=self.front_desk.email.upper())
        queue_booking_event(self.booking, "confirmation")
        self.assertSetEqual(
            self.recipients(), {self.other_staff.email, self.attendee.email, self.front_desk.email}
        )
        desk = Notification.objects.get(recipient_email=self.front_desk.email)
        self.assertEqual(desk.recipient_role, Notification.RecipientRole.PARTICIPANT)
        self.front_desk.is_staff = False
        self.front_desk.save(update_fields=["is_staff"])
        self.assertEqual(send_due_notifications(), 3)
        organizer_mail = next(item for item in mail.outbox if item.to == [self.other_staff.email])
        self.assertIn("/check-in/link/", organizer_mail.body)

    def test_front_desk_requires_active_staff_account_in_approved_domain(self):
        for changes in ({"is_staff": False}, {"is_active": False}):
            with self.subTest(changes=changes):
                Notification.objects.all().delete()
                User.objects.filter(pk=self.front_desk.pk).update(is_staff=True, is_active=True)
                User.objects.filter(pk=self.front_desk.pk).update(**changes)
                queue_booking_event(self.booking, "confirmation")
                self.assertSetEqual(self.recipients(), {self.organizer.email, self.attendee.email})
        with override_settings(BOOKING_FRONT_DESK_EMAIL="other.admin@example.com"):
            User.objects.create_user("other.admin@example.com", is_staff=True)
            queue_booking_event(self.booking, "confirmation")
            self.assertNotIn("other.admin@example.com", self.recipients())

    def test_front_desk_access_is_rechecked_when_queued_copy_is_delivered(self):
        queue_booking_event(self.booking, "confirmation")
        desk = Notification.objects.get(recipient_email=self.front_desk.email)
        User.objects.filter(pk=self.front_desk.pk).update(is_active=False)
        self.assertEqual(send_due_notifications(), 2)
        desk.refresh_from_db()
        self.assertEqual(desk.status, Notification.Status.SKIPPED)
        self.assertIsNone(desk.sent_at)

    def test_routing_changes_skip_previously_queued_front_desk_copies(self):
        with override_settings(BOOKING_FRONT_DESK_EMAIL=self.other_staff.email):
            queue_booking_event(self.booking, "confirmation")
        obsolete = Notification.objects.get(recipient_email=self.other_staff.email)
        self.assertEqual(send_due_notifications(), 2)
        obsolete.refresh_from_db()
        self.assertEqual(obsolete.status, Notification.Status.SKIPPED)

    def test_legacy_broadcast_is_skipped_but_current_participants_and_front_desk_deliver(self):
        for email in (
            self.organizer.email,
            self.attendee.email,
            self.front_desk.email,
            self.other_staff.email,
        ):
            Notification.objects.create(
                reservation=self.booking,
                reservation_revision=self.booking.revision,
                recipient_email=email,
                event_type="change",
                subject="Legacy change",
                body="Meeting changed",
                next_attempt_at=self.now,
            )
        self.assertEqual(send_due_notifications(), 3)
        self.assertSetEqual(
            {message.to[0] for message in mail.outbox},
            {self.organizer.email, self.attendee.email, self.front_desk.email},
        )
        obsolete = Notification.objects.get(recipient_email=self.other_staff.email)
        self.assertEqual(obsolete.status, Notification.Status.SKIPPED)

    def test_removed_participants_including_staff_receive_change_notice(self):
        previous_organizer = self.other_staff.email
        previous_attendee = "removed@transgate.com.np"
        previous_guest = "guest@outside.example"
        queue_booking_event(
            self.booking, "change", extra_recipients=[previous_organizer, previous_attendee, previous_guest]
        )
        self.assertEqual(send_due_notifications(), 6)
        for email in (previous_organizer, previous_attendee, previous_guest):
            with self.subTest(email=email):
                notification = Notification.objects.get(recipient_email=email)
                self.assertEqual(notification.recipient_role, Notification.RecipientRole.PARTICIPANT)
                self.assertEqual(notification.status, Notification.Status.SENT)
        for email in (previous_attendee, previous_guest):
            message = next(item for item in mail.outbox if item.to == [email])
            self.assertIn("Contact organizer", message.body)
            self.assertNotIn("View meeting:", message.body)
            self.assertNotIn("/check-in/link/", message.body)
