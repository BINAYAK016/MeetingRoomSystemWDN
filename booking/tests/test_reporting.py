from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase, TestCase

from booking.models import BookingPolicy, CompanyHoliday, Reservation, Room, User
from booking.services.reporting import _intersection_minutes, _minutes, _subtract, report_data

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
MONDAY = date(2026, 10, 5)


def local_at(day, hour, minute=0):
    return datetime.combine(day, time(hour, minute), LOCAL_TZ)


class ReportIntervalTests(SimpleTestCase):
    def test_closure_union_clips_partial_and_overlapping_ranges_once(self):
        windows = [(local_at(MONDAY, 9), local_at(MONDAY, 17))]
        closures = [
            (local_at(MONDAY, 8), local_at(MONDAY, 10)),
            (local_at(MONDAY, 9, 30), local_at(MONDAY, 11)),
            (local_at(MONDAY, 16), local_at(MONDAY, 18)),
        ]
        remaining = _subtract(windows, closures)
        self.assertEqual(remaining, [(local_at(MONDAY, 11), local_at(MONDAY, 16))])
        self.assertEqual(_minutes(remaining), 300)

    def test_multi_day_closure_subtracts_only_working_window_segments(self):
        next_day = MONDAY + timedelta(days=1)
        windows = [
            (local_at(MONDAY, 9), local_at(MONDAY, 17)),
            (local_at(next_day, 9), local_at(next_day, 17)),
        ]
        remaining = _subtract(windows, [(local_at(MONDAY, 16), local_at(next_day, 10))])
        self.assertEqual(_minutes(remaining), 840)

    def test_overlapping_meeting_intervals_are_unioned_before_utilization(self):
        windows = [(local_at(MONDAY, 9), local_at(MONDAY, 17))]
        meetings = [(local_at(MONDAY, 8), local_at(MONDAY, 13)), (local_at(MONDAY, 12), local_at(MONDAY, 18))]
        self.assertEqual(_intersection_minutes(meetings, windows), 480)


class ReportingTests(TestCase):
    def setUp(self):
        BookingPolicy.objects.get_or_create(pk=1)
        self.user = User.objects.create_user("person@wdn.com.np")
        self.room = Room.objects.create(name="Board room", location="WDN", floor="3", capacity=8)

    def booking(self, starts, ends, status=Reservation.Status.COMPLETED, department="Operations"):
        return Reservation.objects.create(
            room=self.room,
            organizer=self.user,
            created_by=self.user,
            kind=Reservation.Kind.BOOKING,
            status=status,
            starts_at=starts,
            ends_at=ends,
            occupied_from=starts,
            occupied_until=ends,
            title="Planning",
            department=department,
            checked_in_at=starts
            if status in (Reservation.Status.COMPLETED, Reservation.Status.CHECKED_IN)
            else None,
        )

    def closure(self, starts, ends, status=Reservation.Status.BLOCKED):
        return Reservation.objects.create(
            room=self.room,
            created_by=self.user,
            kind=Reservation.Kind.BLOCK,
            status=status,
            starts_at=starts,
            ends_at=ends,
            occupied_from=starts,
            occupied_until=ends,
            block_reason="Maintenance",
        )

    def row(self, start=MONDAY, end=MONDAY):
        records, rows, departments, organizers = report_data(start, end)
        return records, rows[0], departments, organizers

    def test_active_closure_reduces_available_working_minutes(self):
        self.booking(local_at(MONDAY, 9), local_at(MONDAY, 11))
        self.closure(local_at(MONDAY, 12), local_at(MONDAY, 14))
        records, row, departments, organizers = self.row()
        self.assertEqual(len(records), 1)
        self.assertEqual(row["available_minutes"], 360)
        self.assertEqual(row["occupied_minutes"], 120)
        self.assertEqual(row["utilization"], 33.3)
        self.assertEqual(departments, [("Operations", 1)])
        self.assertEqual(organizers, [(self.user.email, 1)])

    def test_cancelled_closure_does_not_reduce_available_hours(self):
        self.closure(local_at(MONDAY, 9), local_at(MONDAY, 17), Reservation.Status.BLOCK_CANCELLED)
        _, row, _, _ = self.row()
        self.assertEqual(row["available_minutes"], 480)

    def test_holiday_and_weekend_meetings_do_not_inflate_utilization(self):
        CompanyHoliday.objects.create(date=MONDAY, name="Holiday")
        self.booking(local_at(MONDAY, 9), local_at(MONDAY, 17))
        saturday = date(2026, 10, 10)
        self.booking(local_at(saturday, 9), local_at(saturday, 17))
        records, row, _, _ = self.row(MONDAY, saturday)
        self.assertEqual(len(records), 2)
        self.assertEqual(row["available_minutes"], 4 * 480)
        self.assertEqual(row["occupied_minutes"], 0)
        self.assertEqual(row["utilization"], 0)

    def test_outside_office_hours_are_clipped_and_never_exceed_100_percent(self):
        self.booking(local_at(MONDAY, 0), local_at(MONDAY, 23))
        _, row, _, _ = self.row()
        self.assertEqual(row["occupied_minutes"], 480)
        self.assertEqual(row["utilization"], 100)

    def test_verified_meeting_that_begins_before_range_contributes_only_overlap(self):
        sunday = MONDAY - timedelta(days=1)
        self.booking(local_at(sunday, 23), local_at(MONDAY, 10))
        records, row, _, _ = self.row()
        self.assertEqual(records, [])
        self.assertEqual(row["bookings"], 0)
        self.assertEqual(row["occupied_minutes"], 60)
        self.assertEqual(row["utilization"], 12.5)

    def test_room_closed_all_day_has_zero_bookable_minutes(self):
        self.closure(local_at(MONDAY, 8), local_at(MONDAY, 18))
        _, row, _, _ = self.row()
        self.assertEqual(row["available_minutes"], 0)
        self.assertEqual(row["utilization"], 0)

    def test_only_checked_in_or_completed_bookings_contribute_minutes(self):
        self.booking(local_at(MONDAY, 9), local_at(MONDAY, 10), Reservation.Status.CONFIRMED)
        self.booking(local_at(MONDAY, 10), local_at(MONDAY, 11), Reservation.Status.CANCELLED)
        self.booking(local_at(MONDAY, 11), local_at(MONDAY, 12), Reservation.Status.NO_SHOW)
        self.booking(local_at(MONDAY, 12), local_at(MONDAY, 13), Reservation.Status.CHECKED_IN)
        self.booking(local_at(MONDAY, 13), local_at(MONDAY, 14), Reservation.Status.COMPLETED)
        records, row, _, _ = self.row()
        self.assertEqual(len(records), 5)
        self.assertEqual(row["completed"], 1)
        self.assertEqual(row["cancelled"], 1)
        self.assertEqual(row["no_shows"], 1)
        self.assertEqual(row["occupied_minutes"], 120)

    def test_booking_counts_use_nepal_date_not_utc_date(self):
        early = self.booking(local_at(MONDAY, 0, 15), local_at(MONDAY, 1, 15), department="")
        records, row, departments, _ = self.row()
        self.assertEqual([item.pk for item in records], [early.pk])
        self.assertEqual(row["bookings"], 1)
        self.assertEqual(early.starts_at.astimezone(ZoneInfo("UTC")).date(), MONDAY - timedelta(days=1))
        self.assertEqual(departments, [("Unspecified", 1)])

    def test_invalid_or_excessive_range_is_rejected(self):
        with self.assertRaises(ValueError):
            report_data(MONDAY, MONDAY - timedelta(days=1))
        with self.assertRaises(ValueError):
            report_data(MONDAY, MONDAY + timedelta(days=367))
