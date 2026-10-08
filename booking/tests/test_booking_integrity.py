from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.db import IntegrityError, close_old_connections, connections, transaction
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from booking.forms import PolicyForm, RoomForm
from booking.models import (
    AuditEvent,
    BookingAttendee,
    BookingPolicy,
    BookingSeries,
    CompanyHoliday,
    Notification,
    Reservation,
    Room,
    User,
)
from booking.services.bookings import (
    BookingError,
    cancel_booking,
    create_booking,
    occurrence_dates,
    update_booking,
)
from booking.services.checkin import CheckInError, complete_finished, manual_checkin

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 5, 8, tzinfo=LOCAL_TZ)
MEETING_DATE = date(2026, 10, 6)


def booking_data(room, **changes):
    values = {
        "room": room,
        "date": MEETING_DATE,
        "start_time": time(11),
        "end_time": time(12),
        "title": "Planning",
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


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BookingIntegrityTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.user = User.objects.create_user("person@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Board room", location="WDN", floor="3", capacity=8)

    def test_invalid_dates_and_times_rejected_without_partial_records(self):
        invalid = [
            {"date": NOW.date(), "start_time": time(7), "end_time": time(8)},
            {"date": NOW.date() + timedelta(days=15)},
            {"date": date(2026, 10, 10)},
            {"start_time": time(12), "end_time": time(11)},
            {"start_time": time(11), "end_time": time(11)},
            {"start_time": time(8), "end_time": time(9)},
            {"start_time": time(16), "end_time": time(18)},
            {"start_time": time(11, 10), "end_time": time(12, 10)},
        ]
        for changes in invalid:
            with self.subTest(changes=changes), self.assertRaises(BookingError):
                create_booking(booking_data(self.room, **changes), actor=self.user)
        self.assertFalse(Reservation.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="booking_created").exists())

    def test_daily_series_skips_weekends_and_holidays(self):
        CompanyHoliday.objects.create(date=date(2026, 10, 8), name="Company holiday")
        items = create_booking(
            booking_data(self.room, recurrence="daily", until_date=date(2026, 10, 13)), actor=self.user
        )
        self.assertEqual(
            [timezone.localtime(item.starts_at, LOCAL_TZ).date() for item in items],
            [date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 9), date(2026, 10, 12), date(2026, 10, 13)],
        )
        self.assertEqual(BookingSeries.objects.count(), 1)

    def test_daily_series_with_no_working_days_has_clear_error(self):
        with self.assertRaisesMessage(BookingError, "no company working days"):
            create_booking(
                booking_data(
                    self.room, date=date(2026, 10, 10), recurrence="daily", until_date=date(2026, 10, 11)
                ),
                actor=self.user,
            )
        self.assertFalse(BookingSeries.objects.exists())

    def test_staff_override_keeps_explicit_non_working_day_occurrences(self):
        items = create_booking(
            booking_data(
                self.room,
                date=date(2026, 10, 10),
                recurrence="daily",
                until_date=date(2026, 10, 11),
                override_reason="Approved weekend meeting",
            ),
            actor=self.staff,
            staff=True,
        )
        self.assertEqual(len(items), 2)
        self.assertTrue(all(item.override_reason == "Approved weekend meeting" for item in items))

    def test_recurring_conflict_rolls_back_every_new_occurrence(self):
        original = create_booking(booking_data(self.room, date=date(2026, 10, 7)), actor=self.user)[0]
        baseline = (Notification.objects.count(), BookingAttendee.objects.count(), AuditEvent.objects.count())
        with self.assertRaises(BookingError):
            create_booking(
                booking_data(self.room, recurrence="daily", until_date=date(2026, 10, 8)), actor=self.user
            )
        self.assertEqual(list(Reservation.objects.values_list("pk", flat=True)), [original.pk])
        self.assertFalse(BookingSeries.objects.exists())
        self.assertEqual(
            (Notification.objects.count(), BookingAttendee.objects.count(), AuditEvent.objects.count()),
            baseline,
        )

    def test_monthly_series_creates_only_occurrences_within_horizon(self):
        items = create_booking(
            booking_data(self.room, recurrence="monthly", until_date=date(2026, 10, 19)), actor=self.user
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].series.frequency, "monthly")

    def test_occurrence_generation_handles_date_boundaries_and_rejects_bad_range(self):
        self.assertEqual(occurrence_dates(date.max, date.max, "daily"), [date.max])
        self.assertEqual(occurrence_dates(date.max, date.max, "monthly"), [date.max])
        with self.assertRaises(BookingError):
            occurrence_dates(MEETING_DATE, MEETING_DATE - timedelta(days=1), "daily")
        with self.assertRaises(BookingError):
            occurrence_dates(MEETING_DATE, MEETING_DATE, "unsupported")

    def test_edit_reads_locked_current_room_active_status(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        stale_room = Room.objects.get(pk=self.room.pk)
        Room.objects.filter(pk=self.room.pk).update(is_active=False)
        with self.assertRaisesMessage(BookingError, "inactive"):
            update_booking(item.pk, booking_data(stale_room, title="Changed"), actor=self.user)
        item.refresh_from_db()
        self.assertEqual(item.title, "Planning")

    def test_create_and_edit_read_locked_current_capacity(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        stale_room = Room.objects.get(pk=self.room.pk)
        Room.objects.filter(pk=self.room.pk).update(capacity=1)
        with self.assertRaisesMessage(BookingError, "seats 1"):
            update_booking(item.pk, booking_data(stale_room, title="Changed"), actor=self.user)
        with self.assertRaisesMessage(BookingError, "seats 1"):
            create_booking(booking_data(stale_room, start_time=time(13), end_time=time(14)), actor=self.user)
        self.assertEqual(Reservation.objects.count(), 1)

    def test_organizer_listed_as_attendee_is_counted_only_once(self):
        self.room.capacity = 2
        self.room.save(update_fields=["capacity"])
        item = create_booking(
            booking_data(self.room, attendees=[self.user.email, "colleague@wdn.com.np"]), actor=self.user
        )[0]
        self.assertEqual(item.attendees.count(), 2)

    def test_edit_conflict_keeps_original_booking_attendees_and_notifications(self):
        original = create_booking(booking_data(self.room), actor=self.user)[0]
        create_booking(booking_data(self.room, start_time=time(13), end_time=time(14)), actor=self.user)
        notices = Notification.objects.count()
        with self.assertRaises(BookingError):
            update_booking(
                original.pk,
                booking_data(
                    self.room, start_time=time(13), end_time=time(14), attendees=["replacement@wdn.com.np"]
                ),
                actor=self.user,
            )
        original.refresh_from_db()
        self.assertEqual(timezone.localtime(original.starts_at, LOCAL_TZ).time(), time(11))
        self.assertEqual(list(original.attendees.values_list("email", flat=True)), ["colleague@wdn.com.np"])
        self.assertEqual(Notification.objects.count(), notices)

    def test_cancel_releases_time_and_invalidates_checkin_tokens(self):
        from booking.models import EmailToken

        item = create_booking(booking_data(self.room), actor=self.user)[0]
        token = EmailToken.objects.create(
            user=self.user,
            reservation=item,
            email=self.user.email,
            purpose="check_in",
            token_hash="a" * 64,
            expires_at=item.starts_at + timedelta(minutes=15),
        )
        cancel_booking(item.pk, actor=self.user)
        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)
        replacement = create_booking(booking_data(self.room), actor=self.user)[0]
        self.assertNotEqual(item.pk, replacement.pk)

    def test_service_authorization_rejects_foreign_booking_edit_and_cancel(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        other = User.objects.create_user("other@wdn.com.np")
        with self.assertRaises(BookingError):
            update_booking(item.pk, booking_data(self.room), actor=other)
        with self.assertRaises(BookingError):
            cancel_booking(item.pk, actor=other)
        item.refresh_from_db()
        self.assertEqual(item.status, Reservation.Status.PENDING)

    def test_persisted_booking_retains_nepal_wall_time(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        item.refresh_from_db()
        self.assertEqual(
            timezone.localtime(item.starts_at, LOCAL_TZ), datetime(2026, 10, 6, 11, tzinfo=LOCAL_TZ)
        )
        self.assertEqual(item.starts_at.astimezone(ZoneInfo("UTC")).strftime("%H:%M"), "05:15")

    def test_policy_rejects_immediate_deadline_and_impossible_steps(self):
        policy = BookingPolicy.objects.get(pk=1)
        values = {field: getattr(policy, field) for field in PolicyForm.Meta.fields}
        for change in (
            {"check_in_minutes": 0},
            {"minimum_minutes": 0},
            {"slot_minutes": 0},
            {"check_in_minutes": 31},
            {"slot_minutes": 20},
            {"advance_days": 367},
        ):
            with self.subTest(change=change):
                self.assertFalse(PolicyForm({**values, **change}, instance=policy).is_valid())
        with self.assertRaises(IntegrityError), transaction.atomic():
            BookingPolicy.objects.filter(pk=1).update(check_in_minutes=0)

    def test_room_facilities_validate_lengths_and_deduplicate_names(self):
        values = {"name": "Room", "location": "WDN", "floor": "2", "capacity": 8, "is_active": True}
        form = RoomForm({**values, "facilities_text": "Projector, projector; Whiteboard"})
        self.assertTrue(form.is_valid(), form.errors)
        self.assertEqual(form.cleaned_data["facilities_text"], "Projector\nWhiteboard")
        invalid = RoomForm({**values, "facilities_text": "x" * 121})
        self.assertFalse(invalid.is_valid())
        self.assertIn("facilities_text", invalid.errors)

    def test_calendar_does_not_offer_closed_or_past_slots(self):
        self.client.force_login(self.user)
        for day, expected in (
            (date(2026, 10, 10), "weekend"),
            (date(2026, 10, 2), "Past date"),
            (date(2026, 10, 20), "booking window"),
        ):
            response = self.client.get(reverse("calendar"), {"date": day.isoformat(), "view": "day"})
            self.assertEqual(response.status_code, 200)
            self.assertIn(expected, response.context["date_unavailable_reason"])
            self.assertTrue(
                all(not cell["available"] for slot in response.context["slots"] for cell in slot["cells"])
            )
        CompanyHoliday.objects.create(date=MEETING_DATE, name="Annual holiday")
        response = self.client.get(reverse("calendar"), {"date": MEETING_DATE.isoformat(), "view": "day"})
        self.assertIn("Annual holiday", response.context["date_unavailable_reason"])

    def test_calendar_preserves_buffer_and_staff_can_open_bookings(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        self.client.force_login(self.staff)
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = self.staff.auth_version
        session.save()
        response = self.client.get(reverse("calendar"), {"date": MEETING_DATE.isoformat(), "view": "day"})
        slot = next(slot for slot in response.context["slots"] if slot["time"].time() == time(12))
        self.assertEqual(slot["cells"][0]["occupied"]["url"], reverse("booking-detail", args=[item.pk]))
        self.assertFalse(slot["cells"][0]["available"])
        self.assertTrue(slot["cells"][0]["can_open"])

    def test_manual_checkin_missing_or_closure_ids_fail_gracefully(self):
        with self.assertRaisesMessage(CheckInError, "unavailable"):
            manual_checkin(999999, actor=self.staff)

    def test_completion_updates_timestamp_without_changing_history(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        item.status = Reservation.Status.CHECKED_IN
        item.checked_in_at = item.starts_at
        item.save(update_fields=["status", "checked_in_at"])
        completed_at = item.ends_at + timedelta(minutes=1)
        self.assertEqual(complete_finished(completed_at), 1)
        item.refresh_from_db()
        self.assertEqual(item.status, Reservation.Status.COMPLETED)
        self.assertEqual(item.updated_at, completed_at)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BookingConcurrencyTests(TransactionTestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.user = User.objects.create_user("person@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Room A", location="WDN", floor="3", capacity=8)
        self.other_room = Room.objects.create(name="Room B", location="WDN", floor="3", capacity=8)

    def concurrently(self, functions):
        barrier = Barrier(len(functions))

        def attempt(function):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                function()
                return "success"
            except BookingError:
                return "rejected"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(attempt, function) for function in functions]
            return [future.result(timeout=30) for future in futures]

    def test_service_simultaneous_create_commits_one_booking_and_one_notification_set(self):
        results = self.concurrently(
            [
                lambda: create_booking(booking_data(self.room), actor=self.user),
                lambda: create_booking(booking_data(self.room), actor=self.user),
            ]
        )
        self.assertCountEqual(results, ["success", "rejected"])
        self.assertEqual(Reservation.objects.count(), 1)
        self.assertEqual(BookingAttendee.objects.count(), 1)
        self.assertEqual(AuditEvent.objects.filter(action="booking_created").count(), 1)
        self.assertEqual(Notification.objects.filter(event_type="request").count(), 2)
        self.assertFalse(Notification.objects.filter(event_type="confirmation").exists())

    def test_service_simultaneous_edits_into_one_slot_commit_one_change(self):
        first = create_booking(booking_data(self.room), actor=self.user)[0]
        second = create_booking(
            booking_data(self.room, start_time=time(13), end_time=time(14)), actor=self.user
        )[0]
        target = booking_data(self.room, start_time=time(15), end_time=time(16))
        results = self.concurrently(
            [
                lambda: update_booking(first.pk, target, actor=self.user),
                lambda: update_booking(second.pk, target, actor=self.user),
            ]
        )
        self.assertCountEqual(results, ["success", "rejected"])
        self.assertEqual(
            Reservation.objects.filter(starts_at=datetime.combine(MEETING_DATE, time(15), LOCAL_TZ)).count(),
            1,
        )
        self.assertEqual(AuditEvent.objects.filter(action="booking_modified").count(), 1)

    def test_edit_and_cancel_same_booking_leave_cancelled_consistent_state(self):
        item = create_booking(booking_data(self.room), actor=self.user)[0]
        results = self.concurrently(
            [
                lambda: update_booking(
                    item.pk,
                    booking_data(self.other_room, start_time=time(13), end_time=time(14)),
                    actor=self.user,
                ),
                lambda: cancel_booking(item.pk, actor=self.user),
            ]
        )
        self.assertIn("success", results)
        item.refresh_from_db()
        self.assertEqual(item.status, Reservation.Status.CANCELLED)
        self.assertIsNotNone(item.cancelled_at)
        self.assertEqual(AuditEvent.objects.filter(action="booking_cancelled").count(), 1)

    def test_simultaneous_staff_bookings_for_first_time_organizer_create_one_user(self):
        organizer = "newperson@wdn.com.np"
        results = self.concurrently(
            [
                lambda: create_booking(
                    booking_data(self.room, organizer_email=organizer), actor=self.staff, staff=True
                ),
                lambda: create_booking(
                    booking_data(self.other_room, organizer_email=organizer), actor=self.staff, staff=True
                ),
            ]
        )
        self.assertEqual(results, ["success", "success"])
        user = User.objects.get(email=organizer)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(Reservation.objects.filter(organizer=user).count(), 2)
