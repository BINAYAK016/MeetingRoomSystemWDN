import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from threading import Event
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.db import connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from booking.models import (
    AuditEvent,
    BookingPolicy,
    BookingSeries,
    Department,
    EmailToken,
    Notification,
    Reservation,
    Room,
    User,
)
from booking.services.bookings import BookingError, create_booking, update_booking
from booking.services.notifications import send_due_notifications

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 5, 8, tzinfo=LOCAL_TZ)
DAY = date(2026, 10, 6)


def booking_values(room, **changes):
    values = {
        "room": room,
        "date": DAY,
        "start_time": time(11),
        "end_time": time(12),
        "title": "Room policy meeting",
        "description": "",
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
    values.update(changes)
    return values


class RoomApprovalFixtures:
    def setUp(self):
        super().setUp()
        Department.objects.get_or_create(name="Operations")
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.employee = User.objects.create_user("employee@wdn.com.np")
        self.other = User.objects.create_user("other@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.reviewed_room = Room.objects.create(name="Reviewed", location="WDN", floor="2", capacity=8)
        self.automatic_room = Room.objects.create(
            name="Automatic", location="WDN", floor="2", capacity=8, requires_approval=False
        )


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_READY=True)
class RoomApprovalPolicyTests(RoomApprovalFixtures, TestCase):
    def created(self, room=None, *, staff=False, **changes):
        return create_booking(
            booking_values(room or self.reviewed_room, **changes),
            actor=self.staff if staff else self.employee,
            staff=staff,
        )[0]

    def test_default_room_requires_approval_and_employee_request_remains_pending(self):
        self.assertTrue(self.reviewed_room.requires_approval)
        booking = self.created()
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_by_id)
        self.assertIsNone(booking.approved_at)
        self.assertSetEqual(set(booking.notification_set.values_list("event_type", flat=True)), {"request"})
        audit = AuditEvent.objects.get(action="booking_created", target_id=booking.pk)
        self.assertFalse(audit.details["automatic_approval"])
        self.assertTrue(audit.details["requires_approval"])

    def test_unchecked_room_automatically_approves_and_sends_confirmation_with_checkin(self):
        booking = self.created(self.automatic_room)
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertIsNone(booking.approved_by_id)
        self.assertEqual(booking.approved_at, NOW)
        self.assertSetEqual(
            set(booking.notification_set.values_list("event_type", flat=True)), {"confirmation"}
        )
        self.assertSetEqual(
            set(booking.notification_set.values_list("recipient_email", flat=True)),
            {self.employee.email, self.staff.email, "attendee@wdn.com.np"},
        )
        self.assertEqual(send_due_notifications(NOW), 3)
        organizer_mail = next(message for message in mail.outbox if message.to == [self.employee.email])
        self.assertIn("/check-in/", organizer_mail.body)
        self.assertEqual(EmailToken.objects.filter(reservation=booking, purpose="check_in").count(), 1)
        audit = AuditEvent.objects.get(action="booking_created", target_id=booking.pk)
        self.assertTrue(audit.details["automatic_approval"])
        self.assertFalse(audit.details["requires_approval"])
        self.assertFalse(AuditEvent.objects.filter(action="booking_approved", target_id=booking.pk).exists())

    def test_staff_creates_approved_booking_in_both_room_policies(self):
        for room in (self.reviewed_room, self.automatic_room):
            with self.subTest(room=room.name):
                booking = self.created(room, staff=True)
                self.assertEqual(booking.status, Reservation.Status.APPROVED)
                self.assertEqual(booking.approved_by_id, self.staff.pk)
                self.assertEqual(booking.approved_at, NOW)
                self.assertEqual(booking.notification_set.filter(event_type="confirmation").count(), 2)
                self.assertFalse(AuditEvent.objects.get(target_id=booking.pk).details["automatic_approval"])

    def test_every_recurring_occurrence_uses_selected_room_approval_policy(self):
        for room, status in (
            (self.reviewed_room, Reservation.Status.PENDING),
            (self.automatic_room, Reservation.Status.APPROVED),
        ):
            with self.subTest(room=room.name):
                bookings = create_booking(
                    booking_values(room, recurrence="daily", until_date=DAY + timedelta(days=2)),
                    actor=self.employee,
                )
                self.assertEqual(len(bookings), 3)
                self.assertTrue(all(booking.status == status for booking in bookings))
                self.assertEqual(len({booking.series_id for booking in bookings}), 1)
                event = "request" if status == Reservation.Status.PENDING else "confirmation"
                self.assertSetEqual(
                    set(
                        Notification.objects.filter(reservation__in=bookings).values_list(
                            "event_type", flat=True
                        )
                    ),
                    {event},
                )

    def test_room_policy_change_leaves_all_existing_statuses_and_notifications_untouched(self):
        pending = self.created()
        approved = self.created(self.automatic_room)
        before = list(Reservation.objects.values("id", "status", "revision", "approved_at", "approved_by_id"))
        notices = list(Notification.objects.values("id", "status", "reservation_revision"))
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=False)
        Room.objects.filter(pk=self.automatic_room.pk).update(requires_approval=True)
        self.assertEqual(
            list(Reservation.objects.values("id", "status", "revision", "approved_at", "approved_by_id")),
            before,
        )
        self.assertEqual(list(Notification.objects.values("id", "status", "reservation_revision")), notices)
        self.assertEqual(Reservation.objects.get(pk=pending.pk).status, "pending")
        self.assertEqual(Reservation.objects.get(pk=approved.pk).status, "approved")

    def test_employee_edit_in_unchecked_room_replaces_previous_human_approval(self):
        booking = self.created(self.automatic_room, staff=True, organizer_email=self.employee.email)
        booking = update_booking(
            booking.pk, booking_values(self.automatic_room, title="Updated"), actor=self.employee
        )
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertIsNone(booking.approved_by_id)
        self.assertEqual(booking.approved_at, NOW)
        self.assertEqual(booking.revision, 2)
        self.assertTrue(booking.notification_set.filter(event_type="change", reservation_revision=2).exists())
        audit = AuditEvent.objects.get(action="booking_modified", target_id=booking.pk)
        self.assertTrue(audit.details["automatic_approval"])

    def test_employee_move_to_checked_room_returns_booking_to_pending(self):
        booking = self.created(self.automatic_room)
        booking = update_booking(booking.pk, booking_values(self.reviewed_room), actor=self.employee)
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_by_id)
        self.assertIsNone(booking.approved_at)
        self.assertTrue(
            booking.notification_set.filter(event_type="request", reservation_revision=2).exists()
        )
        self.assertFalse(
            booking.notification_set.filter(event_type="confirmation", status="pending").exists()
        )

    def test_employee_move_to_unchecked_room_confirms_pending_request(self):
        booking = self.created()
        booking = update_booking(booking.pk, booking_values(self.automatic_room), actor=self.employee)
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertIsNone(booking.approved_by_id)
        self.assertEqual(booking.approved_at, NOW)
        self.assertTrue(
            booking.notification_set.filter(event_type="confirmation", reservation_revision=2).exists()
        )
        self.assertFalse(booking.notification_set.filter(event_type="request", status="pending").exists())

    def test_noop_employee_save_preserves_pending_after_room_becomes_unchecked(self):
        booking = self.created()
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=False)
        count = Notification.objects.count()
        booking = update_booking(booking.pk, booking_values(self.reviewed_room), actor=self.employee)
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_at)
        self.assertEqual(booking.revision, 1)
        self.assertEqual(Notification.objects.count(), count)
        self.assertFalse(AuditEvent.objects.filter(action="booking_modified").exists())

    def test_noop_employee_save_preserves_human_approval_after_room_policy_change(self):
        booking = self.created(staff=True, organizer_email=self.employee.email)
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=False)
        booking = update_booking(booking.pk, booking_values(self.reviewed_room), actor=self.employee)
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertEqual(booking.approved_by_id, self.staff.pk)
        self.assertEqual(booking.revision, 1)

    def test_staff_edit_of_pending_request_requires_review_only_in_checked_room(self):
        for room, status in (
            (self.reviewed_room, Reservation.Status.PENDING),
            (self.automatic_room, Reservation.Status.APPROVED),
        ):
            with self.subTest(room=room.name):
                booking = self.created(self.reviewed_room, start_time=time(13), end_time=time(14))
                booking = update_booking(
                    booking.pk,
                    booking_values(
                        room,
                        start_time=time(13),
                        end_time=time(14),
                        title="Staff edit",
                        organizer_email=self.employee.email,
                    ),
                    actor=self.staff,
                    staff=True,
                )
                self.assertEqual(booking.status, status)
                self.assertIsNone(booking.approved_by_id)
                self.assertEqual(booking.approved_at, NOW if status == "approved" else None)
                # Free the source slot for the next subtest without triggering a booking workflow.
                booking.status = Reservation.Status.CANCELLED
                booking.save(update_fields=["status"])

    def test_staff_edit_of_approved_booking_keeps_existing_review_in_both_room_policies(self):
        for room in (self.reviewed_room, self.automatic_room):
            with self.subTest(room=room.name):
                booking = self.created(room, staff=True)
                booking = update_booking(
                    booking.pk, booking_values(room, title="Staff revision"), actor=self.staff, staff=True
                )
                self.assertEqual(booking.status, Reservation.Status.APPROVED)
                self.assertEqual(booking.approved_by_id, self.staff.pk)
                self.assertEqual(booking.approved_at, NOW)
                self.assertTrue(
                    booking.notification_set.filter(event_type="change", reservation_revision=2).exists()
                )

    def test_edit_supersedes_pending_failed_sending_jobs_and_old_checkin_tokens(self):
        booking = self.created(self.automatic_room)
        for index, status in enumerate(("pending", "failed", "sending")):
            Notification.objects.create(
                reservation=booking,
                reservation_revision=1,
                recipient_email=f"old{index}@wdn.com.np",
                event_type="change",
                subject="Old revision",
                body="Old revision",
                status=status,
                next_attempt_at=NOW,
            )
        token = EmailToken.objects.create(
            reservation=booking,
            user=self.employee,
            email=self.employee.email,
            purpose="check_in",
            token_hash=hashlib.sha256(b"old-token").hexdigest(),
            expires_at=booking.starts_at,
        )
        update_booking(
            booking.pk, booking_values(self.automatic_room, title="New revision"), actor=self.employee
        )
        self.assertFalse(
            booking.notification_set.filter(reservation_revision=1).exclude(status="skipped").exists()
        )
        self.assertTrue(booking.notification_set.filter(reservation_revision=2, event_type="change").exists())
        token.refresh_from_db()
        self.assertEqual(token.consumed_at, NOW)

    def test_stale_room_instance_and_forged_service_fields_do_not_control_approval(self):
        self.reviewed_room.requires_approval = False
        booking = self.created(
            self.reviewed_room, requires_approval=False, status="approved", approved_by=self.employee
        )
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_by_id)
        self.automatic_room.requires_approval = True
        booking = self.created(self.automatic_room, requires_approval=True, status="pending")
        self.assertEqual(booking.status, Reservation.Status.APPROVED)

    def test_substantive_edit_reads_current_policy_instead_of_submitted_room_instance(self):
        booking = self.created()
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=False)
        booking = update_booking(
            booking.pk,
            booking_values(self.reviewed_room, title="Edited after policy change"),
            actor=self.employee,
        )
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertIsNone(booking.approved_by_id)
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=True)
        booking = update_booking(
            booking.pk, booking_values(self.reviewed_room, title="Needs review again"), actor=self.employee
        )
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_at)

    def test_automatic_approval_does_not_relax_capacity_time_activity_or_ownership_guards(self):
        for changes in (
            {"external_attendee_count": 8},
            {"start_time": time(8)},
            {"date": DAY + timedelta(days=30)},
        ):
            with self.subTest(changes=changes), self.assertRaises(BookingError):
                self.created(self.automatic_room, **changes)
        booking = self.created(self.automatic_room)
        with self.assertRaises(BookingError):
            update_booking(
                booking.pk, booking_values(self.automatic_room, title="Forged edit"), actor=self.other
            )
        with self.assertRaises(BookingError):
            create_booking(booking_values(self.reviewed_room), actor=self.employee, staff=True)
        Room.objects.filter(pk=self.automatic_room.pk).update(is_active=False)
        with self.assertRaises(BookingError):
            self.created(self.automatic_room, start_time=time(13), end_time=time(14))

    def test_conflict_rolls_back_entire_automatic_series_and_its_confirmation_mail(self):
        existing = self.created(self.automatic_room, date=DAY + timedelta(days=1))
        notices = Notification.objects.count()
        with self.assertRaises(BookingError):
            create_booking(
                booking_values(self.automatic_room, recurrence="daily", until_date=DAY + timedelta(days=2)),
                actor=self.employee,
            )
        self.assertEqual(list(Reservation.objects.values_list("id", flat=True)), [existing.pk])
        self.assertEqual(Notification.objects.count(), notices)
        self.assertFalse(BookingSeries.objects.exists())

    def post_values(self, room, **changes):
        values = booking_values(room, **changes)
        values["room"] = room.pk
        values["attendees"] = "attendee@wdn.com.np"
        values["until_date"] = ""
        return values

    def test_availability_exposes_approval_flag_without_allowing_query_override(self):
        self.client.force_login(self.employee)
        response = self.client.get(
            reverse("booking-availability"),
            {
                "date": DAY.isoformat(),
                "start_time": "11:00",
                "end_time": "12:00",
                "recurrence": "none",
                "requires_approval": "false",
            },
        )
        self.assertEqual(response.status_code, 200)
        flags = {room["id"]: room["requires_approval"] for room in response.json()["rooms"]}
        self.assertTrue(flags[self.reviewed_room.pk])
        self.assertFalse(flags[self.automatic_room.pk])

    def test_booking_post_ignores_forged_approval_fields_and_reports_actual_status(self):
        self.client.force_login(self.employee)
        for room, status, text in (
            (self.reviewed_room, "pending", "Waiting for administrator approval"),
            (self.automatic_room, "approved", "does not require administrator approval"),
        ):
            with self.subTest(room=room.name):
                response = self.client.post(
                    reverse("booking-new"),
                    self.post_values(
                        room,
                        requires_approval="false",
                        status="approved",
                        approved_by=self.employee.pk,
                        organizer_email=self.other.email,
                    ),
                    follow=True,
                )
                self.assertEqual(response.status_code, 200)
                booking = Reservation.objects.get(room=room)
                self.assertEqual(booking.status, status)
                self.assertEqual(booking.organizer_id, self.employee.pk)
                self.assertIsNone(booking.approved_by_id)
                self.assertContains(response, text)

    def test_edit_post_autoapproves_after_policy_change_and_reports_confirmation(self):
        booking = self.created()
        Room.objects.filter(pk=self.reviewed_room.pk).update(requires_approval=False)
        self.client.force_login(self.employee)
        response = self.client.post(
            reverse("booking-edit", args=[booking.pk]),
            self.post_values(self.reviewed_room, title="New title"),
            follow=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "updated and confirmed")
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.APPROVED)


class RoomApprovalConcurrencyTests(RoomApprovalFixtures, TransactionTestCase):
    def apply_policy_while_booking_waits(self, room, operation):
        from booking.services import bookings

        actor_locked = Event()
        original_lock = bookings._locked_users

        def lock_users(*ids):
            users = original_lock(*ids)
            actor_locked.set()
            return users

        def reserve():
            try:
                return operation().pk
            finally:
                connections.close_all()

        with patch("booking.services.bookings._locked_users", side_effect=lock_users):
            with ThreadPoolExecutor(max_workers=1) as pool:
                with transaction.atomic():
                    locked = Room.objects.select_for_update().get(pk=room.pk)
                    locked.requires_approval = False
                    locked.save(update_fields=["requires_approval"])
                    future = pool.submit(reserve)
                    self.assertTrue(actor_locked.wait(timeout=15))
                    self.assertFalse(future.done())
                booking_id = future.result(timeout=30)
        booking = Reservation.objects.get(pk=booking_id)
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertIsNone(booking.approved_by_id)
        self.assertEqual(booking.approved_at, NOW)

    def test_create_reads_policy_committed_by_concurrent_room_update(self):
        self.apply_policy_while_booking_waits(
            self.reviewed_room,
            lambda: create_booking(booking_values(self.reviewed_room), actor=self.employee)[0],
        )

    def test_edit_reads_policy_committed_by_concurrent_room_update(self):
        booking = create_booking(booking_values(self.reviewed_room), actor=self.employee)[0]
        self.apply_policy_while_booking_waits(
            self.reviewed_room,
            lambda: update_booking(
                booking.pk,
                booking_values(self.reviewed_room, title="Concurrent policy edit"),
                actor=self.employee,
            ),
        )


class RoomApprovalMigrationTests(TransactionTestCase):
    migrate_from = [("booking", "0010_room_photo")]
    migrate_to = [("booking", "0011_room_requires_approval")]

    def setUp(self):
        super().setUp()
        self.latest_schema = MigrationExecutor(connection).loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(self.latest_schema))

    def test_existing_rooms_require_approval_without_changing_existing_bookings(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old = executor.loader.project_state(self.migrate_from).apps
        user = old.get_model("booking", "User").objects.create(email="legacy@wdn.com.np", password="!")
        room = old.get_model("booking", "Room").objects.create(
            name="Legacy", location="WDN", floor="2", capacity=8, photo="rooms/photos/legacy.jpg"
        )
        reservations = old.get_model("booking", "Reservation")
        for index, status in enumerate(("pending", "approved", "cancelled")):
            starts = NOW + timedelta(days=1, hours=3 + index * 2)
            reservations.objects.create(
                room_id=room.pk,
                organizer_id=user.pk,
                created_by_id=user.pk,
                kind="booking",
                status=status,
                title=f"Legacy {status}",
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
                occupied_from=starts,
                occupied_until=starts + timedelta(hours=1, minutes=15),
                revision=4,
                approved_at=NOW if status == "approved" else None,
                approved_by_id=user.pk if status == "approved" else None,
            )
        before = list(reservations.objects.order_by("pk").values())
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        current = executor.loader.project_state(self.migrate_to).apps
        rooms = current.get_model("booking", "Room")
        migrated_room = rooms.objects.get(pk=room.pk)
        self.assertTrue(migrated_room.requires_approval)
        self.assertEqual(migrated_room.photo, "rooms/photos/legacy.jpg")
        self.assertEqual(
            list(current.get_model("booking", "Reservation").objects.order_by("pk").values()), before
        )
        new_room = rooms.objects.create(name="New room", location="WDN", floor="2", capacity=8)
        self.assertTrue(new_room.requires_approval)
