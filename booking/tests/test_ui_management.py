import hashlib
import io
from datetime import time, timedelta
from unittest.mock import patch

from django.contrib.sessions.models import Session
from django.db import OperationalError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from openpyxl import load_workbook

from booking.models import AuditEvent, EmailToken, Reservation, Room, RoomFacility, User
from booking.services.bookings import create_booking


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class UserInterfaceTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user("person@wdn.com.np", department="Operations")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Board room", location="WDN", floor="3", capacity=12)
        self.day = timezone.localdate() + timedelta(days=1)
        while self.day.weekday() >= 5:
            self.day += timedelta(days=1)

    def sign_in_staff(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = self.staff.auth_version
        session.save()

    def booking(self, **changes):
        data = {
            "room": self.room,
            "date": self.day,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Planning",
            "description": "",
            "meeting_type": "internal",
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": [],
            "refreshments_requested": False,
            "front_desk_notes": "",
            "recurrence": "none",
            "until_date": None,
        }
        data.update(changes)
        return create_booking(data, actor=self.employee)[0]

    def test_profile_updates_only_owned_nonsecurity_fields(self):
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("profile"),
            {
                "first_name": "Binayak",
                "last_name": "Employee",
                "department": "Finance",
                "email": self.staff.email,
                "is_staff": "on",
                "is_active": "",
                "auth_version": "900",
            },
        )
        self.assertRedirects(response, reverse("profile"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Finance")
        self.assertEqual(self.employee.email, "person@wdn.com.np")
        self.assertFalse(self.employee.is_staff)
        self.assertTrue(self.employee.is_active)
        self.assertEqual(self.employee.auth_version, 1)
        self.assertTrue(AuditEvent.objects.filter(actor=self.employee, action="profile_updated").exists())

    def test_profile_validation_preserves_data(self):
        self.client.force_login(self.employee)
        response = self.client.post(reverse("profile"), {"department": "x" * 121})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "at most 120")
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Operations")

    def test_security_headers_and_private_page_caching(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("profile"))
        self.assertIn("script-src 'self'", response["Content-Security-Policy"])
        self.assertIn("form-action 'self'", response["Content-Security-Policy"])
        self.assertEqual(response["Permissions-Policy"], "camera=(), microphone=(), geolocation=()")
        self.assertEqual(response["X-Frame-Options"], "DENY")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", response["Cache-Control"])

    def test_room_filters_combine_and_exclude_inactive(self):
        RoomFacility.objects.create(room=self.room, name="Projector")
        Room.objects.create(name="Small room", location="WDN", floor="1", capacity=4)
        Room.objects.create(name="Inactive Board", location="WDN", floor="2", capacity=20, is_active=False)
        self.client.force_login(self.employee)
        response = self.client.get(
            reverse("rooms"), {"q": "board", "capacity": 8, "location": "WDN", "facility": "Projector"}
        )
        self.assertEqual([item.pk for item in response.context["rooms"]], [self.room.pk])
        self.assertContains(response, "Projector")
        self.assertNotContains(response, "Inactive Board")
        self.assertEqual(self.client.get(reverse("room-detail", args=[9999])).status_code, 404)

    def test_lists_keep_all_results_and_filters_while_paginating(self):
        self.sign_in_staff()
        User.objects.bulk_create([User(email=f"team{i:03}@wdn.com.np") for i in range(60)])
        response = self.client.get(reverse("staff-users"), {"q": "team", "page": 2})
        self.assertEqual(response.context["page_obj"].paginator.count, 60)
        self.assertEqual(len(response.context["users"]), 25)
        self.assertContains(response, "q=team&amp;page=3")

    def test_staff_booking_filters_and_employee_upcoming_history(self):
        booking = self.booking()
        self.client.force_login(self.employee)
        response = self.client.get(reverse("my-bookings"))
        self.assertContains(response, booking.title)
        Reservation.objects.filter(pk=booking.pk).update(status="cancelled")
        self.assertNotContains(self.client.get(reverse("my-bookings")), booking.title)
        self.assertContains(self.client.get(reverse("my-bookings"), {"period": "history"}), booking.title)
        self.sign_in_staff()
        response = self.client.get(
            reverse("staff-bookings"),
            {"q": "plan", "status": "cancelled", "room": self.room.pk, "from": self.day.isoformat()},
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(
            self.client.get(reverse("staff-bookings"), {"status": "confirmed"})
            .context["page_obj"]
            .paginator.count,
            0,
        )

    def test_user_validation_and_access_change_invalidate_old_mfa(self):
        self.sign_in_staff()
        response = self.client.post(
            reverse("staff-user-save"), {"email": "outsider@example.com", "is_active": "on"}
        )
        self.assertContains(response, "wdn.com.np")
        self.assertFalse(User.objects.filter(email="outsider@example.com").exists())
        target = User.objects.create_user("otherdesk@wdn.com.np", is_staff=True)
        EmailToken.objects.create(
            purpose="staff",
            email=target.email,
            user=target,
            token_hash="a" * 64,
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        self.client.post(reverse("staff-user-save"), {"email": target.email, "is_active": "on"})
        target.refresh_from_db()
        self.assertFalse(target.is_staff)
        self.assertEqual(target.auth_version, 2)
        self.assertIsNotNone(EmailToken.objects.get(user=target).consumed_at)
        self.client.force_login(target)
        session = self.client.session
        session["staff_verified"], session["staff_auth_version"] = True, 1
        session.save()
        self.assertRedirects(self.client.get(reverse("staff-dashboard")), reverse("staff-login"))

    def test_staff_cannot_remove_own_access(self):
        self.sign_in_staff()
        self.client.post(reverse("staff-user-save"), {"email": self.staff.email})
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.is_staff)
        self.assertTrue(self.staff.is_active)

    def test_access_management_reuses_case_insensitive_existing_identity(self):
        self.sign_in_staff()
        target = User.objects.create(email="UPPER@wdn.com.np", is_active=False)
        response = self.client.post(
            reverse("staff-user-save"),
            {"email": "upper@wdn.com.np", "is_active": "on", "department": "Operations"},
        )
        self.assertRedirects(response, reverse("staff-users"))
        self.assertEqual(User.objects.filter(email__iexact="upper@wdn.com.np").count(), 1)
        target.refresh_from_db()
        self.assertTrue(target.is_active)
        self.assertEqual(target.department, "Operations")

    def test_room_reactivation_and_facility_validation(self):
        self.sign_in_staff()
        data = {
            "name": self.room.name,
            "location": "WDN",
            "floor": "3",
            "capacity": "15",
            "is_active": "on",
            "facilities_text": "Projector\nWhiteboard",
        }
        self.room.is_active = False
        self.room.save()
        self.assertEqual(
            self.client.post(reverse("staff-room-edit", args=[self.room.pk]), data).status_code, 302
        )
        self.room.refresh_from_db()
        self.assertTrue(self.room.is_active)
        self.assertEqual(self.room.facilities.count(), 2)
        response = self.client.post(
            reverse("staff-room-edit", args=[self.room.pk]), {**data, "facilities_text": "a" * 121}
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.room.facilities.count(), 2)

    def test_excel_user_text_is_literal_and_web_output_is_escaped(self):
        booking = self.booking(title='=HYPERLINK("https://example.invalid", "Click")', department="=1+1")
        self.sign_in_staff()
        response = self.client.get(
            reverse("staff-report-excel"), {"from": self.day.isoformat(), "to": self.day.isoformat()}
        )
        workbook = load_workbook(io.BytesIO(response.content), data_only=False)
        self.assertEqual(workbook["Bookings"]["I2"].value, booking.title)
        self.assertEqual(workbook["Bookings"]["I2"].data_type, "s")
        self.assertEqual(workbook["Departments"]["A2"].data_type, "s")
        Reservation.objects.filter(pk=booking.pk).update(title='<script>alert("xss")</script>')
        response = self.client.get(reverse("booking-detail", args=[booking.pk]))
        self.assertNotContains(response, '<script>alert("xss")</script>')
        self.assertContains(response, "&lt;script&gt;")

    def test_early_checkin_does_not_remove_session_link(self):
        booking = self.booking()
        raw = "early-checkin-test-token"
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        EmailToken.objects.create(
            purpose="check_in",
            email=self.employee.email,
            reservation=booking,
            token_hash=token_hash,
            expires_at=booking.ends_at,
        )
        self.client.get(reverse("checkin-link", args=[raw]))
        decoded = Session.objects.get(session_key=self.client.session.session_key).get_decoded()
        self.assertEqual(decoded["pending_checkin_token"], token_hash)
        self.assertNotIn(raw, str(decoded))
        response = self.client.post(reverse("checkin-confirm"))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.client.session["pending_checkin_token"], token_hash)
        with patch(
            "booking.services.checkin.timezone.now", return_value=booking.starts_at + timedelta(minutes=1)
        ):
            self.assertEqual(self.client.post(reverse("checkin-confirm")).status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "checked_in")
        self.assertNotIn("pending_checkin_token", self.client.session)

    def test_database_checkin_digest_is_not_accepted_as_external_link(self):
        booking = self.booking()
        raw = "private-checkin-link-token"
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        token = EmailToken.objects.create(
            purpose="check_in",
            email=self.employee.email,
            reservation=booking,
            token_hash=token_hash,
            expires_at=booking.ends_at,
        )
        with patch(
            "booking.services.checkin.timezone.now", return_value=booking.starts_at + timedelta(minutes=1)
        ):
            self.client.get(reverse("checkin-link", args=[token_hash]))
            self.assertEqual(self.client.post(reverse("checkin-confirm")).status_code, 400)
            token.refresh_from_db()
            booking.refresh_from_db()
            self.assertIsNone(token.consumed_at)
            self.assertEqual(booking.status, "confirmed")
            self.client.get(reverse("checkin-link", args=[raw]))
            self.assertEqual(self.client.post(reverse("checkin-confirm")).status_code, 200)
        booking.refresh_from_db()
        self.assertEqual(booking.status, "checked_in")

    @override_settings(DEBUG=False)
    def test_errors_and_database_outage_show_safe_pages(self):
        response = self.client.get("/missing-page/")
        self.assertEqual(response.status_code, 404)
        self.assertContains(response, "This page is unavailable", status_code=404)
        with patch(
            "booking.views.Room.objects.filter",
            side_effect=OperationalError("secret database connection details"),
        ):
            self.client.force_login(self.employee)
            response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "temporarily unavailable", status_code=503)
        self.assertNotContains(response, "secret database", status_code=503)
