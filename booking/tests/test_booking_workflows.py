import hashlib
import re
from datetime import time, timedelta
from unittest.mock import patch

from django.core import mail
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from booking.models import EmailToken, Notification, Reservation, Room, User
from booking.services.bookings import BookingError, approve_booking, create_booking, occurrence_dates
from booking.services.checkin import confirm_checkin, release_due_no_shows
from booking.services.notifications import queue_due_reminders, send_due_notifications


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BookingWorkflowTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("person@wdn.com.np")
        self.room = Room.objects.create(name="Board room", location="WDN", floor="3", capacity=8)
        self.day = timezone.localdate() + timedelta(days=1)
        while self.day.weekday() >= 5:
            self.day += timedelta(days=1)

    def data(self, **changes):
        values = {
            "room": self.room,
            "date": self.day,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Weekly planning",
            "description": "",
            "meeting_type": "internal",
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": ["colleague@wdn.com.np"],
            "refreshments_requested": False,
            "front_desk_notes": "",
            "recurrence": "none",
            "until_date": None,
        }
        values.update(changes)
        return values

    def approve(self, booking):
        staff = User.objects.create_user("approver@wdn.com.np", is_staff=True)
        request = RequestFactory().post("/staff/")
        request.user = staff
        request.session = {"staff_verified": True, "staff_auth_version": staff.auth_version}
        return approve_booking(booking.pk, actor=staff, request=request)

    def test_booking_conflict_and_notifications(self):
        booking = create_booking(self.data(), actor=self.user)[0]
        self.assertEqual(booking.status, "pending")
        self.assertEqual(Notification.objects.filter(event_type="request").count(), 1)
        self.assertFalse(Notification.objects.filter(event_type="confirmation").exists())
        with self.assertRaises(BookingError):
            create_booking(self.data(start_time=time(12), end_time=time(13)), actor=self.user)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_daily_recurrence_stays_within_window(self):
        bookings = create_booking(
            self.data(recurrence="daily", until_date=self.day + timedelta(days=2)), actor=self.user
        )
        self.assertEqual(len(bookings), sum((self.day + timedelta(days=n)).weekday() < 5 for n in range(3)))
        self.assertTrue(all(item.series_id == bookings[0].series_id for item in bookings))
        with self.assertRaises(BookingError):
            create_booking(
                self.data(recurrence="weekly", until_date=self.day + timedelta(days=30)), actor=self.user
            )

    def test_monthly_recurrence_clamps_short_month(self):
        from datetime import date

        self.assertEqual(
            occurrence_dates(date(2027, 1, 31), date(2027, 3, 31), "monthly"),
            [date(2027, 1, 31), date(2027, 2, 28), date(2027, 3, 31)],
        )

    def test_reminder_link_and_checkin(self):
        booking = self.approve(create_booking(self.data(), actor=self.user)[0])
        reminder_time = booking.starts_at - timedelta(minutes=45)
        self.assertEqual(queue_due_reminders(now=reminder_time), 3)
        with patch("booking.services.notifications.timezone.now", return_value=reminder_time):
            self.assertGreater(send_due_notifications(now=reminder_time), 0)
        reminder = next(
            message
            for message in mail.outbox
            if "reminder" in message.subject and message.to == [self.user.email]
        )
        raw = re.search(r"/check-in/link/([^/]+)/", reminder.body).group(1)
        self.assertEqual(
            EmailToken.objects.get(
                purpose="check_in", token_hash=hashlib.sha256(raw.encode()).hexdigest()
            ).token_hash,
            hashlib.sha256(raw.encode()).hexdigest(),
        )
        with patch(
            "booking.services.checkin.timezone.now", return_value=booking.starts_at + timedelta(minutes=1)
        ):
            confirm_checkin(raw)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "checked_in")
        self.assertEqual(release_due_no_shows(now=booking.starts_at + timedelta(minutes=20)), 0)

    def test_missed_checkin_releases_room(self):
        booking = self.approve(create_booking(self.data(), actor=self.user)[0])
        self.assertEqual(release_due_no_shows(now=booking.starts_at + timedelta(minutes=16)), 1)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "no_show")
        self.assertEqual(booking.cancellation_reason, "No check-in before the deadline")

    def test_employee_and_staff_pages(self):
        self.client.force_login(self.user)
        for name in ("home", "rooms", "calendar", "booking-new", "my-bookings"):
            self.assertEqual(self.client.get(reverse(name)).status_code, 200, name)
        self.assertContains(self.client.get(reverse("room-detail", args=[self.room.pk])), "Board room")
        self.assertEqual(self.client.get(reverse("calendar") + "?view=month").status_code, 200)
        self.assertEqual(self.client.get(reverse("staff-dashboard")).status_code, 302)
        staff = User.objects.create_user(
            "desk@wdn.com.np", password="StrongDeskPassphrase2026!", is_staff=True
        )
        self.client.force_login(staff)
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = staff.auth_version
        session.save()
        for name in (
            "staff-dashboard",
            "staff-rooms",
            "staff-bookings",
            "staff-blocks",
            "staff-policy",
            "staff-holidays",
            "staff-users",
            "staff-reports",
            "staff-audit",
        ):
            response = self.client.get(reverse(name))
            self.assertEqual(response.status_code, 200, name)
        self.assertEqual(self.client.get(reverse("staff-report-excel")).status_code, 200)

    def test_booking_form_create_edit_and_cancel(self):
        self.client.force_login(self.user)
        form_data = {
            "room": self.room.pk,
            "date": self.day.isoformat(),
            "start_time": "11:00",
            "end_time": "12:00",
            "title": "Planning",
            "description": "Agenda",
            "meeting_type": "internal",
            "guest_company_name": "",
            "external_attendee_count": "0",
            "department": "Operations",
            "attendees": "colleague@wdn.com.np",
            "front_desk_notes": "",
            "recurrence": "none",
        }
        response = self.client.post(reverse("booking-new"), form_data)
        self.assertEqual(response.status_code, 302)
        booking = Reservation.objects.get(kind="booking")
        self.assertEqual(booking.title, "Planning")
        edit_data = {**form_data, "title": "Updated planning", "start_time": "13:00", "end_time": "14:00"}
        response = self.client.post(reverse("booking-edit", args=[booking.pk]), edit_data)
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.title, "Updated planning")
        response = self.client.post(reverse("booking-cancel", args=[booking.pk]), {"reason": "Plans changed"})
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "cancelled")

    def test_conflict_form_shows_error_and_queues_notice(self):
        create_booking(self.data(), actor=self.user)
        self.client.force_login(self.user)
        response = self.client.post(
            reverse("booking-new"),
            {
                "room": self.room.pk,
                "date": self.day.isoformat(),
                "start_time": "11:00",
                "end_time": "12:00",
                "title": "Other meeting",
                "meeting_type": "internal",
                "external_attendee_count": "0",
                "recurrence": "none",
            },
        )
        self.assertContains(response, "unavailable")
        self.assertTrue(
            Notification.objects.filter(event_type="conflict", recipient_email=self.user.email).exists()
        )

    def test_employee_cannot_open_or_modify_someone_elses_booking(self):
        booking = create_booking(self.data(), actor=self.user)[0]
        other = User.objects.create_user("other@wdn.com.np")
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("booking-detail", args=[booking.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("booking-edit", args=[booking.pk])).status_code, 404)
        self.assertEqual(self.client.post(reverse("booking-cancel", args=[booking.pk])).status_code, 404)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "pending")

    def test_inactive_room_and_invalid_duration_are_rejected(self):
        with self.assertRaises(BookingError):
            create_booking(self.data(end_time=time(11, 15)), actor=self.user)
        self.room.is_active = False
        self.room.save(update_fields=["is_active"])
        with self.assertRaises(BookingError):
            create_booking(self.data(), actor=self.user)

    def test_email_failure_is_recorded_without_losing_booking(self):
        booking = create_booking(self.data(), actor=self.user)[0]
        with patch("booking.services.notifications.deliver_mail", side_effect=OSError("relay down")):
            self.assertEqual(send_due_notifications(limit=1), 0)
        self.assertTrue(Notification.objects.filter(reservation=booking, status="failed").exists())
        booking.refresh_from_db()
        self.assertEqual(booking.status, "pending")

    def test_staff_room_management_requires_second_factor(self):
        staff = User.objects.create_user(
            "desk@wdn.com.np", password="StrongDeskPassphrase2026!", is_staff=True
        )
        self.client.force_login(staff)
        response = self.client.post(
            reverse("staff-room-new"),
            {
                "name": "New room",
                "location": "WDN",
                "floor": "2",
                "capacity": "10",
                "facilities_text": "Projector",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertFalse(Room.objects.filter(name="New room").exists())
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = staff.auth_version
        session.save()
        response = self.client.post(
            reverse("staff-room-new"),
            {
                "name": "New room",
                "location": "WDN",
                "floor": "2",
                "capacity": "10",
                "facilities_text": "Projector",
                "is_active": "on",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Room.objects.filter(name="New room", facilities__name="Projector").exists())
        created = Room.objects.get(name="New room")
        response = self.client.post(
            reverse("staff-room-edit", args=[created.pk]),
            {
                "name": "New room",
                "location": "WDN",
                "floor": "2",
                "capacity": "12",
                "facilities_text": "Whiteboard",
            },
        )
        self.assertEqual(response.status_code, 302)
        created.refresh_from_db()
        self.assertFalse(created.is_active)
        self.assertEqual(created.capacity, 12)
        self.assertTrue(created.facilities.filter(name="Whiteboard").exists())

    def test_staff_password_and_email_code(self):
        staff = User.objects.create_user(
            "desk@wdn.com.np", password="StrongDeskPassphrase2026!", is_staff=True
        )
        response = self.client.post(
            reverse("staff-login"), {"email": staff.email, "password": "StrongDeskPassphrase2026!"}
        )
        self.assertRedirects(response, reverse("staff-code"))
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group()
        self.assertNotIn(code, EmailToken.objects.get(purpose="staff").token_hash)
        self.assertRedirects(
            self.client.post(reverse("staff-code"), {"code": code}), reverse("staff-dashboard")
        )
        self.assertTrue(self.client.session["staff_verified"])
