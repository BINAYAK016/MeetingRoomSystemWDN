from datetime import time, timedelta
from unittest.mock import patch

from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode

from booking.models import AuditEvent, Reservation, Room, User
from booking.services.bookings import create_booking


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ApprovalRouteTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user("requester@transgate.com.np", department="Operations")
        self.other = User.objects.create_user("other@wdn.com.np")
        self.staff = User.objects.create_user("reviewer@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Review room", location="WDN", floor="3", capacity=12)
        self.day = timezone.localdate() + timedelta(days=1)
        while self.day.weekday() >= 5:
            self.day += timedelta(days=1)
        self.data = {
            "room": self.room,
            "date": self.day,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Private planning request",
            "description": "Private meeting notes",
            "meeting_type": "internal",
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": ["attendee@wdn.com.np"],
            "refreshments_requested": False,
            "front_desk_notes": "",
            "recurrence": "none",
            "until_date": None,
        }
        self.booking = create_booking(self.data, actor=self.employee)[0]

    def staff_login(self, client=None):
        client = client or self.client
        client.force_login(self.staff)
        session = client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = self.staff.auth_version
        session.save()

    def post_data(self):
        return {
            **self.data,
            "room": self.room.pk,
            "date": self.day.isoformat(),
            "start_time": "13:00",
            "end_time": "14:00",
            "attendees": "attendee@wdn.com.np",
            "until_date": "",
        }

    def test_employee_request_is_pending_and_visible_in_upcoming(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse("booking-new"), self.post_data(), follow=True)
        self.assertContains(response, "Booking request submitted. Waiting for administrator approval.")
        created = Reservation.objects.latest("pk")
        self.assertEqual(created.status, Reservation.Status.PENDING)
        self.assertIsNone(created.approved_by_id)
        self.assertContains(self.client.get(reverse("my-bookings")), "Pending")
        self.assertNotContains(response, "Approve request")

    def test_empty_and_invalid_forms_report_errors_without_saving(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse("booking-new"), {})
        self.assertContains(response, "This field is required")
        self.assertEqual(Reservation.objects.count(), 1)
        self.staff_login()
        for route in ["staff-room-new", "staff-block-new", "staff-policy"]:
            with self.subTest(route=route):
                self.assertContains(self.client.post(reverse(route), {}), "This field is required")

    def test_only_verified_staff_can_review_or_call_actions(self):
        for user in [None, self.employee, self.other, self.staff]:
            self.client.logout()
            if user:
                self.client.force_login(user)
            self.assertRedirects(self.client.get(reverse("staff-bookings-pending")), reverse("staff-login"))
            for route in ["staff-booking-approve", "staff-booking-reject"]:
                response = self.client.post(reverse(route, args=[self.booking.pk]), {"reason": "Denied"})
                self.assertRedirects(response, reverse("staff-login"))
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.status, Reservation.Status.PENDING)

    def test_review_actions_require_post_and_csrf(self):
        self.staff_login()
        for route in ["staff-booking-approve", "staff-booking-reject"]:
            self.assertEqual(self.client.get(reverse(route, args=[self.booking.pk])).status_code, 405)
        protected = Client(enforce_csrf_checks=True)
        self.staff_login(protected)
        for route in ["staff-booking-approve", "staff-booking-reject"]:
            self.assertEqual(
                protected.post(reverse(route, args=[self.booking.pk]), {"reason": "Denied"}).status_code,
                403,
            )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.PENDING)

    def test_approval_and_repeated_approval_preserve_state(self):
        self.staff_login()
        url = reverse("staff-booking-approve", args=[self.booking.pk])
        self.assertRedirects(self.client.post(url), reverse("booking-detail", args=[self.booking.pk]))
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.APPROVED)
        self.assertEqual(self.booking.approved_by_id, self.staff.pk)
        self.assertIsNotNone(self.booking.approved_at)
        self.assertContains(self.client.post(url, follow=True), "Only pending booking requests")
        self.assertEqual(AuditEvent.objects.filter(action="booking_approved").count(), 1)

    def test_rejection_reason_required_bounded_escaped_and_private(self):
        self.staff_login()
        url = reverse("staff-booking-reject", args=[self.booking.pk])
        for invalid in ["", "   ", "x" * 501]:
            response = self.client.post(url, {"reason": invalid})
            self.assertEqual(response.status_code, 400)
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.status, Reservation.Status.PENDING)
        reason = '<script>alert("reason")</script> Room needed for another meeting.'
        self.assertEqual(self.client.post(url, {"reason": reason}).status_code, 302)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.REJECTED)
        self.assertEqual(self.booking.rejection_reason, reason)
        self.client.force_login(self.employee)
        detail_url = reverse("booking-detail", args=[self.booking.pk])
        response = self.client.get(detail_url)
        self.assertContains(response, "Room needed for another meeting.")
        self.assertContains(response, "&lt;script&gt;")
        self.assertNotContains(response, '<script>alert("reason")</script>')
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(detail_url).status_code, 404)

    def test_pending_list_cannot_be_overridden_and_has_request_details(self):
        self.staff_login()
        response = self.client.get(reverse("staff-bookings-pending"), {"status": "approved"})
        self.assertContains(response, self.booking.title)
        self.assertContains(response, self.employee.email)
        self.assertEqual(response.context["status"], Reservation.Status.PENDING)
        detail = self.client.get(reverse("booking-detail", args=[self.booking.pk]))
        for text in [
            "Requester",
            "Requested",
            "Private meeting notes",
            "attendee@wdn.com.np",
            "Approve request",
        ]:
            self.assertContains(detail, text)

    def test_other_employee_cannot_view_edit_or_cancel_request(self):
        self.client.force_login(self.other)
        for route in ["booking-detail", "booking-edit"]:
            self.assertEqual(self.client.get(reverse(route, args=[self.booking.pk])).status_code, 404)
        for route in ["booking-edit", "booking-cancel"]:
            self.assertEqual(
                self.client.post(reverse(route, args=[self.booking.pk]), self.post_data()).status_code, 404
            )
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.PENDING)

    def test_pending_calendar_reserves_time_without_exposing_private_details(self):
        self.client.force_login(self.other)
        response = self.client.get(reverse("calendar"), {"date": self.day.isoformat(), "view": "day"})
        self.assertNotContains(response, self.booking.title)
        self.assertNotContains(response, self.employee.email)
        self.assertNotContains(response, "Private meeting notes")
        occupied = [cell for slot in response.context["slots"] for cell in slot["cells"] if cell["occupied"]]
        self.assertTrue(occupied)
        self.assertTrue(all(not cell["available"] and not cell["can_open"] for cell in occupied))
        self.assertContains(response, "Awaiting approval")
        self.assertContains(response, "Meeting buffer")

    def test_calendar_uses_same_room_snapshot_during_concurrent_activation(self):
        late_room = Room.objects.create(name="Recently activated", location="WDN", floor="4", capacity=12)
        create_booking({**self.data, "room": late_room}, actor=self.employee)
        Room.objects.filter(pk=late_room.pk).update(is_active=False)
        original_filter = Reservation.objects.filter

        def activate_before_booking_query(*args, **kwargs):
            Room.objects.filter(pk=late_room.pk).update(is_active=True)
            return original_filter(*args, **kwargs)

        self.client.force_login(self.employee)
        with patch(
            "booking.booking_views.Reservation.objects.filter", side_effect=activate_before_booking_query
        ):
            response = self.client.get(reverse("calendar"), {"date": self.day.isoformat(), "view": "day"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual([room.pk for room in response.context["rooms"]], [self.room.pk])
        self.assertNotContains(response, late_room.name)
        refreshed = self.client.get(reverse("calendar"), {"date": self.day.isoformat(), "view": "day"})
        self.assertContains(refreshed, late_room.name)

    def test_employee_edit_of_approved_booking_requires_new_review(self):
        self.staff_login()
        self.client.post(reverse("staff-booking-approve", args=[self.booking.pk]))
        self.client.force_login(self.employee)
        data = self.post_data()
        data["title"] = "Changed meeting request"
        response = self.client.post(reverse("booking-edit", args=[self.booking.pk]), data, follow=True)
        self.assertContains(response, "Waiting for administrator approval")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.PENDING)
        self.assertIsNone(self.booking.approved_by_id)
        self.assertIsNone(self.booking.approved_at)

    def test_employee_can_cancel_own_pending_request(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("booking-cancel", args=[self.booking.pk]), {"reason": "No longer needed"}
        )
        self.assertEqual(response.status_code, 302)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.CANCELLED)
        self.staff_login()
        self.assertContains(
            self.client.post(reverse("staff-booking-approve", args=[self.booking.pk]), follow=True),
            "Only pending booking requests",
        )

    def test_all_employee_and_staff_pages_allow_direct_access_and_refresh(self):
        self.client.force_login(self.employee)
        employee_routes = [
            ("home", []),
            ("rooms", []),
            ("room-detail", [self.room.pk]),
            ("calendar", []),
            ("booking-new", []),
            ("my-bookings", []),
            ("booking-detail", [self.booking.pk]),
            ("booking-edit", [self.booking.pk]),
            ("profile", []),
        ]
        for route, args in employee_routes:
            for _ in range(2):
                with self.subTest(route=route):
                    self.assertEqual(self.client.get(reverse(route, args=args)).status_code, 200)
        self.staff_login()
        staff_routes = [
            "staff-dashboard",
            "staff-bookings",
            "staff-bookings-pending",
            "staff-rooms",
            "staff-room-new",
            "staff-blocks",
            "staff-block-new",
            "staff-policy",
            "staff-holidays",
            "staff-users",
            "staff-reports",
            "staff-audit",
        ]
        for route in staff_routes:
            for _ in range(2):
                with self.subTest(route=route):
                    self.assertEqual(self.client.get(reverse(route)).status_code, 200)
        self.assertEqual(self.client.get(reverse("staff-room-edit", args=[self.room.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("staff-report-excel")).status_code, 200)

    def test_malformed_numeric_filters_and_password_link_cannot_raise_500(self):
        self.client.force_login(self.employee)
        self.assertEqual(self.client.get(reverse("rooms"), {"capacity": "²"}).status_code, 200)
        self.staff_login()
        self.assertEqual(self.client.get(reverse("staff-bookings"), {"room": "²"}).status_code, 200)
        self.assertEqual(self.client.get(reverse("staff-users"), {"edit": "²"}).status_code, 200)
        for uid in [urlsafe_base64_encode(b"\xff"), urlsafe_base64_encode(b"abc"), "a" * 1000]:
            response = self.client.get(reverse("staff-set-password", args=[uid, "invalid"]))
            self.assertEqual(response.status_code, 404)
