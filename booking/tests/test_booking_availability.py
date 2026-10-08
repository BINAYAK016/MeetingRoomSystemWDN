from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError, transaction
from django.test import TestCase, override_settings
from django.urls import reverse

from booking.forms import BookingForm
from booking.models import BookingPolicy, CompanyHoliday, Reservation, Room, RoomFacility, User
from booking.services.bookings import BookingError, create_booking, update_booking

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 8, 8, tzinfo=LOCAL_TZ)
DAY = date(2026, 10, 9)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BookingAvailabilityTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.policy, _ = BookingPolicy.objects.get_or_create(pk=1)
        self.user = User.objects.create_user("person@wdn.com.np")
        self.other = User.objects.create_user("other@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Board room", location="WDN", floor="3", capacity=8)
        self.free_room = Room.objects.create(name="Meeting room", location="WDN", floor="2", capacity=4)
        self.inactive_room = Room.objects.create(
            name="Closed room", location="WDN", floor="1", capacity=10, is_active=False
        )
        RoomFacility.objects.create(room=self.room, name="Projector")
        self.client.force_login(self.user)

    def query(self, **changes):
        values = {"date": DAY.isoformat(), "start_time": "11:00", "end_time": "12:00", "recurrence": "none"}
        values.update(changes)
        return values

    def endpoint(self, **changes):
        return self.client.get(reverse("booking-availability"), self.query(**changes))

    def row(self, response, room=None):
        room = room or self.room
        return next(item for item in response.json()["rooms"] if item["id"] == room.pk)

    def reservation(
        self,
        *,
        status=Reservation.Status.PENDING,
        day=DAY,
        start=time(11),
        end=time(12),
        room=None,
        **changes,
    ):
        begins = datetime.combine(day, start, LOCAL_TZ)
        finishes = datetime.combine(day, end, LOCAL_TZ)
        values = {
            "room": room or self.room,
            "organizer": self.user,
            "created_by": self.user,
            "kind": Reservation.Kind.BOOKING,
            "status": status,
            "starts_at": begins,
            "ends_at": finishes,
            "occupied_from": begins,
            "occupied_until": finishes + timedelta(minutes=15),
            "title": "Private salary discussion",
        }
        if status == Reservation.Status.REJECTED:
            values.update(rejected_at=NOW, rejection_reason="Private rejection reason")
        values.update(changes)
        return Reservation.objects.create(**values)

    def sign_in_staff(self, verified=True):
        self.client.force_login(self.staff)
        if verified:
            session = self.client.session
            session["staff_verified"] = True
            session["staff_auth_version"] = self.staff.auth_version
            session.save()

    def data(self, **changes):
        values = {
            "room": self.room,
            "date": DAY,
            "start_time": time(11),
            "end_time": time(12),
            "title": "Planning",
            "description": "",
            "meeting_type": "internal",
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "",
            "attendees": [],
            "refreshments_requested": False,
            "front_desk_notes": "",
            "recurrence": "none",
            "until_date": None,
        }
        values.update(changes)
        return values

    def test_endpoint_requires_login_and_only_accepts_get(self):
        self.client.logout()
        response = self.endpoint()
        self.assertEqual(response.status_code, 401)
        self.assertFalse(response.json()["ok"])
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(reverse("booking-availability"), self.query()).status_code, 405)

    def test_success_uses_nepal_times_and_active_room_metadata(self):
        response = self.endpoint()
        self.assertEqual(response.status_code, 200)
        payload = response.json()
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["timezone"], "Asia/Kathmandu")
        self.assertEqual(
            payload["occurrences"],
            [
                {
                    "date": "2026-10-09",
                    "starts_at": "2026-10-09T11:00:00+05:45",
                    "ends_at": "2026-10-09T12:00:00+05:45",
                }
            ],
        )
        self.assertEqual({item["id"] for item in payload["rooms"]}, {self.room.pk, self.free_room.pk})
        self.assertEqual(self.row(response)["facilities"], ["Projector"])
        self.assertEqual(self.row(response)["capacity"], 8)
        self.assertTrue(self.row(response)["available"])
        self.assertEqual(self.row(response)["photo_url"], "")
        self.assertIn("no-store", response["Cache-Control"])

    def test_all_occupying_statuses_block_with_no_private_meeting_information(self):
        for status in ("pending", "approved", "checked_in", "completed", "blocked"):
            with self.subTest(status=status):
                extra = {}
                if status == "blocked":
                    extra = {"kind": "block", "organizer": None, "block_reason": "Private closure reason"}
                item = self.reservation(status=status, **extra)
                response = self.endpoint()
                self.assertFalse(self.row(response)["available"])
                conflict = self.row(response)["conflicts"][0]
                self.assertEqual(set(conflict), {"date", "occupied_from", "occupied_until"})
                self.assertEqual(conflict["occupied_until"], "2026-10-09T12:15:00+05:45")
                for private in (item.title, self.user.email, "Private closure reason"):
                    self.assertNotIn(private, response.content.decode())
                item.delete()

    def test_closed_booking_statuses_release_preview_availability(self):
        for status in ("cancelled", "no_show", "rejected", "block_cancelled"):
            with self.subTest(status=status):
                extra = (
                    {"kind": "block", "organizer": None, "block_reason": "Maintenance"}
                    if status == "block_cancelled"
                    else {}
                )
                item = self.reservation(status=status, **extra)
                self.assertTrue(self.row(self.endpoint())["available"])
                item.delete()

    def test_both_existing_and_requested_buffers_are_considered(self):
        self.reservation(start=time(11), end=time(12))
        self.assertFalse(self.row(self.endpoint(start_time="12:00", end_time="13:00"))["available"])
        self.assertTrue(self.row(self.endpoint(start_time="12:15", end_time="13:15"))["available"])
        self.assertFalse(self.row(self.endpoint(start_time="10:00", end_time="11:00"))["available"])
        self.assertTrue(self.row(self.endpoint(start_time="10:00", end_time="10:45"))["available"])

    def test_invalid_schedule_queries_return_meaningful_errors(self):
        invalid = [
            {"date": "invalid"},
            {"start_time": "25:00"},
            {"end_time": "10:00"},
            {"date": "2026-10-07"},
            {"date": "2026-10-23"},
            {"date": "2026-10-10"},
            {"start_time": "08:00", "end_time": "09:00"},
            {"start_time": "11:00", "end_time": "11:15"},
            {"start_time": "11:10", "end_time": "12:10"},
            {"start_time": "11:00:00.001", "end_time": "12:00"},
            {"recurrence": "unsupported"},
            {"recurrence": "weekly"},
            {"recurrence": "weekly", "until_date": "2026-10-08"},
        ]
        for values in invalid:
            with self.subTest(values=values):
                response = self.endpoint(**values)
                self.assertEqual(response.status_code, 400)
                self.assertFalse(response.json()["ok"])
                self.assertTrue(response.json()["error"])
        self.assertFalse(Reservation.objects.exists())

    def test_daily_recurrence_preview_matches_submission_and_skips_closed_days(self):
        CompanyHoliday.objects.create(date=date(2026, 10, 12), name="Company holiday")
        response = self.endpoint(recurrence="daily", until_date="2026-10-13")
        self.assertEqual(
            [item["date"] for item in response.json()["occurrences"]], ["2026-10-09", "2026-10-13"]
        )
        created = create_booking(
            self.data(recurrence="daily", until_date=date(2026, 10, 13)), actor=self.user
        )
        self.assertEqual(
            [item.starts_at.date().isoformat() for item in created],
            [item["date"] for item in response.json()["occurrences"]],
        )

    def test_conflict_on_later_recurring_occurrence_makes_room_unavailable(self):
        self.reservation(day=date(2026, 10, 16))
        response = self.endpoint(recurrence="weekly", until_date="2026-10-16")
        self.assertFalse(self.row(response)["available"])
        self.assertEqual(self.row(response)["conflicts"][0]["date"], "2026-10-16")
        self.assertTrue(self.row(response, self.free_room)["available"])

    def test_preview_excludes_only_authorized_mutable_booking(self):
        item = self.reservation()
        self.assertFalse(self.row(self.endpoint())["available"])
        self.assertTrue(self.row(self.endpoint(booking_id=item.pk))["available"])
        self.client.force_login(self.other)
        self.assertEqual(self.endpoint(booking_id=item.pk).status_code, 404)
        self.sign_in_staff(verified=False)
        self.assertEqual(self.endpoint(booking_id=item.pk).status_code, 404)
        self.sign_in_staff()
        self.assertTrue(self.row(self.endpoint(booking_id=item.pk))["available"])
        Reservation.objects.filter(pk=item.pk).update(status="completed")
        self.assertEqual(self.endpoint(booking_id=item.pk).status_code, 400)

    def test_edit_preview_mirrors_single_occurrence_edit_semantics(self):
        item = self.reservation()
        response = self.endpoint(booking_id=item.pk, recurrence="daily", until_date="2026-10-16")
        self.assertEqual(len(response.json()["occurrences"]), 1)

    def test_invalid_edit_identifiers_fail_gracefully(self):
        for identifier in ("invalid", "-1", "9223372036854775808", "1" * 40, "१२"):
            with self.subTest(identifier=identifier):
                self.assertEqual(self.endpoint(booking_id=identifier).status_code, 400)
        self.assertEqual(self.endpoint(booking_id="9999999").status_code, 404)

    def test_only_verified_staff_can_preview_policy_overrides(self):
        query = {
            "date": "2026-10-10",
            "start_time": "08:10",
            "end_time": "08:20",
            "override_reason": "Approved exception",
        }
        self.assertEqual(self.endpoint(**query).status_code, 400)
        self.sign_in_staff(verified=False)
        self.assertEqual(self.endpoint(**query).status_code, 400)
        self.sign_in_staff()
        self.assertEqual(self.endpoint(**query).status_code, 200)
        self.assertEqual(self.endpoint(**{**query, "override_reason": ""}).status_code, 400)

    def test_read_only_preview_does_not_release_or_mutate_overdue_bookings(self):
        item = self.reservation(day=NOW.date(), start=time(7), end=time(9), status="approved")
        self.endpoint()
        item.refresh_from_db()
        self.assertEqual(item.status, "approved")

    def test_new_and_edit_pages_expose_ui_configuration_and_prefills(self):
        response = self.client.get(
            reverse("booking-new"), {"room": self.room.pk, "date": DAY.isoformat(), "start": "13:00"}
        )
        self.assertEqual(response.context["form"].initial["date"], DAY.isoformat())
        self.assertEqual(response.context["form"].initial["start_time"], "13:00")
        self.assertEqual(response.context["form"].initial["end_time"], "14:00")
        self.assertEqual(response.context["booking_ui"]["today"], "2026-10-08")
        self.assertEqual(response.context["booking_ui"]["latest_date"], "2026-10-22")
        self.assertEqual(response.context["booking_ui"]["availability_url"], reverse("booking-availability"))
        self.assertIsNone(response.context["booking_ui"]["booking_id"])
        self.assertEqual(
            {room.pk for room in response.context["booking_rooms"]}, {self.room.pk, self.free_room.pk}
        )
        item = self.reservation()
        response = self.client.get(reverse("booking-edit", args=[item.pk]))
        self.assertEqual(response.context["booking_ui"]["booking_id"], item.pk)
        self.assertEqual(response.context["form"].initial["start_time"], time(11))
        self.assertNotIn("recurrence", response.context["form"].fields)

    def test_default_duration_fits_short_office_hours(self):
        BookingPolicy.objects.filter(pk=1).update(opens_at=time(9), closes_at=time(9, 45), minimum_minutes=30)
        response = self.client.get(reverse("booking-new"))
        self.assertEqual(response.context["form"].initial["date"], "2026-10-08")
        self.assertEqual(response.context["form"].initial["start_time"], "09:00")
        self.assertEqual(response.context["form"].initial["end_time"], "09:45")

    def test_default_schedule_advances_after_office_hours(self):
        with patch("django.utils.timezone.now", return_value=datetime(2026, 10, 9, 16, 45, tzinfo=LOCAL_TZ)):
            response = self.client.get(reverse("booking-new"))
        self.assertEqual(response.context["form"].initial["date"], "2026-10-12")
        self.assertEqual(response.context["form"].initial["start_time"], "09:00")

    def test_mixed_meeting_type_requires_guest_company_in_form_service_and_database(self):
        data = self.data(meeting_type="mixed")
        form_values = {**data, "room": self.room.pk, "attendees": ""}
        form = BookingForm(form_values)
        self.assertFalse(form.is_valid())
        self.assertIn("guest_company_name", form.errors)
        with self.assertRaisesMessage(BookingError, "guest company"):
            create_booking(data, actor=self.user)
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.reservation(meeting_type="mixed", guest_company_name="")
        item = create_booking({**data, "guest_company_name": "Partner company"}, actor=self.user)[0]
        self.assertEqual(item.meeting_type, "mixed")
        self.assertEqual(item.get_meeting_type_display(), "Internal + External")
        with self.assertRaisesMessage(BookingError, "guest company"):
            update_booking(item.pk, {**data, "guest_company_name": "   "}, actor=self.user)

    def test_server_submission_rechecks_conflict_after_available_preview(self):
        self.assertTrue(self.row(self.endpoint())["available"])
        self.reservation(organizer=self.other)
        with self.assertRaises(BookingError):
            create_booking(self.data(), actor=self.user)

    def test_switching_repeat_to_one_meeting_ignores_stale_until_date_in_form_and_post(self):
        values = {
            **self.data(),
            "room": self.room.pk,
            "attendees": "",
            "recurrence": "none",
            "until_date": NOW.date().isoformat(),
        }
        for stale_until in (NOW.date().isoformat(), "not-a-date"):
            with self.subTest(stale_until=stale_until):
                form = BookingForm({**values, "until_date": stale_until})
                self.assertTrue(form.is_valid(), form.errors)
                self.assertIsNone(form.cleaned_data["until_date"])
        response = self.client.post(reverse("booking-new"), values)
        self.assertEqual(response.status_code, 302)
        item = Reservation.objects.get(kind="booking")
        self.assertEqual(item.status, "pending")
        self.assertIsNone(item.series_id)

    def test_single_meeting_availability_ignores_stale_until_date(self):
        response = self.endpoint(until_date=NOW.date().isoformat())
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["occurrences"]), 1)
