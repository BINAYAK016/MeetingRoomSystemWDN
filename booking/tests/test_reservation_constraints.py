from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier

from django.db import IntegrityError, close_old_connections, connections
from django.test import TestCase, TransactionTestCase

from booking.models import BookingPolicy, Reservation, Room, User
from booking.services.reservations import ReservationConflict, RoomUnavailable, reserve_time

START = datetime(2030, 1, 7, 4, 15, tzinfo=timezone.utc)


class ReservationConstraintTests(TransactionTestCase):
    def setUp(self):
        self.organizer = User.objects.create_user("employee@example.com")
        self.staff = User.objects.create_user("staff@example.com", is_staff=True)
        self.room = Room.objects.create(name="Test room", location="Office", floor="1", capacity=8)

    def booking(self, start=START, minutes=60):
        end = start + timedelta(minutes=minutes)
        return Reservation.objects.create(
            room=self.room,
            organizer=self.organizer,
            created_by=self.organizer,
            kind=Reservation.Kind.BOOKING,
            status=Reservation.Status.CONFIRMED,
            starts_at=start,
            ends_at=end,
            occupied_from=start,
            occupied_until=end + timedelta(minutes=15),
            title="Planning",
        )

    def test_overlap_rejected_and_buffer_boundary_allowed(self):
        self.booking()
        with self.assertRaises(IntegrityError):
            self.booking(START + timedelta(minutes=60))
        self.booking(START + timedelta(minutes=75))
        self.assertEqual(Reservation.objects.count(), 2)

    def test_room_closure_conflicts_with_booking(self):
        self.booking()
        with self.assertRaises(IntegrityError):
            Reservation.objects.create(
                room=self.room,
                created_by=self.staff,
                kind=Reservation.Kind.BLOCK,
                status=Reservation.Status.BLOCKED,
                starts_at=START + timedelta(minutes=30),
                ends_at=START + timedelta(minutes=45),
                occupied_from=START + timedelta(minutes=30),
                occupied_until=START + timedelta(minutes=45),
                block_reason="Cleaning",
            )

    def test_no_show_releases_room_without_deleting_history(self):
        original = self.booking()
        original.status = Reservation.Status.NO_SHOW
        original.save(update_fields=["status"])
        replacement = self.booking()
        self.assertNotEqual(original.pk, replacement.pk)
        self.assertEqual(Reservation.objects.count(), 2)

    def test_application_rejects_inactive_room(self):
        self.room.is_active = False
        self.room.save(update_fields=["is_active"])
        with self.assertRaises(RoomUnavailable):
            self.reserve_booking()

    def test_invalid_time_and_kind_are_rejected(self):
        with self.assertRaises(IntegrityError):
            self.booking(START, minutes=0)
        with self.assertRaises(IntegrityError):
            Reservation.objects.create(
                room=self.room,
                created_by=self.staff,
                kind=Reservation.Kind.BLOCK,
                status=Reservation.Status.CONFIRMED,
                starts_at=START,
                ends_at=START + timedelta(minutes=30),
                occupied_from=START,
                occupied_until=START + timedelta(minutes=30),
                block_reason="Cleaning",
            )

    def test_email_case_is_unique(self):
        with self.assertRaises(IntegrityError):
            User.objects.create_user("EMPLOYEE@example.com")

    def test_simultaneous_attempts_result_in_one_booking(self):
        barrier = Barrier(2)

        def attempt():
            close_old_connections()
            try:
                barrier.wait(timeout=10)
                self.reserve_booking()
                return "created"
            except ReservationConflict:
                return "conflict"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: attempt(), range(2)))

        self.assertCountEqual(results, ["created", "conflict"])
        self.assertEqual(Reservation.objects.count(), 1)

    def reserve_booking(self):
        end = START + timedelta(hours=1)
        return reserve_time(
            room_id=self.room.pk,
            occupied_from=START,
            occupied_until=end + timedelta(minutes=15),
            kind=Reservation.Kind.BOOKING,
            organizer=self.organizer,
            created_by=self.organizer,
            status=Reservation.Status.CONFIRMED,
            starts_at=START,
            ends_at=end,
            title="Planning",
        )


class InitialPolicyTests(TestCase):
    def test_policy_is_seeded_by_migration(self):
        self.assertEqual(BookingPolicy.objects.get(pk=1).advance_days, 14)
