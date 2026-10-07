import hashlib
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, time, timedelta
from threading import Barrier
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.core import mail
from django.db import IntegrityError, close_old_connections, connection, connections, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, TestCase, TransactionTestCase, override_settings

from booking.management.commands.retry_failed_mail import retry_failed_mail
from booking.models import AuditEvent, BookingPolicy, EmailToken, Notification, Reservation, Room, User
from booking.services.bookings import (
    BookingError,
    approve_booking,
    cancel_booking,
    create_booking,
    reject_booking,
    update_booking,
)
from booking.services.checkin import (
    CheckInError,
    confirm_checkin,
    manual_checkin,
    release_due_pending_requests,
)
from booking.services.notifications import queue_due_reminders, send_due_notifications

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 5, 8, tzinfo=LOCAL_TZ)


def booking_values(room, **changes):
    values = {
        "room": room,
        "date": date(2026, 10, 6),
        "start_time": time(11),
        "end_time": time(12),
        "title": "Approval meeting",
        "description": "Discuss the plan",
        "meeting_type": "internal",
        "guest_company_name": "",
        "external_attendee_count": 0,
        "department": "Operations",
        "attendees": ["attendee@transgate.com.np"],
        "refreshments_requested": False,
        "front_desk_notes": "",
        "recurrence": "none",
        "until_date": None,
    }
    values.update(changes)
    return values


def staff_request(user, verified=True):
    request = RequestFactory().post("/staff/")
    request.user = user
    request.session = {"staff_verified": verified, "staff_auth_version": user.auth_version}
    return request


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_READY=True)
class BookingApprovalTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.employee = User.objects.create_user("employee@transgate.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Approval room", location="WDN", floor="2", capacity=8)
        self.request = staff_request(self.staff)

    def pending(self, **changes):
        return create_booking(booking_values(self.room, **changes), actor=self.employee)[0]

    def approve(self, booking):
        return approve_booking(booking.pk, actor=self.staff, request=self.request)

    def reject(self, booking, reason="Room reserved for an urgent visit"):
        return reject_booking(booking.pk, actor=self.staff, request=self.request, reason=reason)

    def test_request_holds_room_and_notifies_requester_and_reviewers_only(self):
        booking = self.pending()
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_by)
        self.assertSetEqual(
            set(Notification.objects.filter(event_type="request").values_list("recipient_email", flat=True)),
            {self.employee.email, self.staff.email},
        )
        self.assertFalse(Notification.objects.filter(event_type="confirmation").exists())
        with self.assertRaises(BookingError):
            self.pending(start_time=time(12), end_time=time(13))
        with self.assertRaises(IntegrityError), transaction.atomic():
            Reservation.objects.create(
                room=self.room,
                organizer=self.employee,
                created_by=self.employee,
                kind="booking",
                status="approved",
                starts_at=booking.starts_at,
                ends_at=booking.ends_at,
                occupied_from=booking.occupied_from,
                occupied_until=booking.occupied_until,
                title="Conflict",
            )

    def test_verified_staff_approval_records_decision_and_sends_confirmation(self):
        booking = self.approve(self.pending())
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertEqual(booking.approved_by, self.staff)
        self.assertEqual(booking.approved_at, NOW)
        self.assertTrue(AuditEvent.objects.filter(action="booking_approved", actor=self.staff).exists())
        self.assertEqual(send_due_notifications(), 3)
        self.assertTrue(all("approved" in message.subject for message in mail.outbox))
        organizer_mail = next(message for message in mail.outbox if message.to == [self.employee.email])
        self.assertIn("/check-in/link/", organizer_mail.body)
        self.assertEqual(Notification.objects.filter(event_type="request", status="skipped").count(), 2)

    def test_staff_created_bookings_are_approved_and_employee_cannot_forge_staff_flag(self):
        with self.assertRaises(BookingError):
            create_booking(booking_values(self.room), actor=self.employee, staff=True)
        booking = create_booking(booking_values(self.room), actor=self.staff, staff=True)[0]
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertEqual(booking.approved_by, self.staff)
        self.assertTrue(Notification.objects.filter(event_type="confirmation").exists())

    def test_approval_and_rejection_require_current_verified_staff(self):
        booking = self.pending()
        invalid = [
            (self.employee, staff_request(self.employee)),
            (self.staff, staff_request(self.staff, verified=False)),
            (self.staff, None),
            (self.staff, staff_request(self.employee)),
        ]
        stale = staff_request(self.staff)
        stale.session["staff_auth_version"] = self.staff.auth_version + 1
        invalid.append((self.staff, stale))
        for actor, request in invalid:
            with self.subTest(actor=actor.email, request=request):
                with self.assertRaises(BookingError):
                    approve_booking(booking.pk, actor=actor, request=request)
                with self.assertRaises(BookingError):
                    reject_booking(booking.pk, actor=actor, request=request, reason="Not allowed")
        User.objects.filter(pk=self.staff.pk).update(is_staff=False)
        with self.assertRaises(BookingError):
            self.approve(booking)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.PENDING)

    def test_rejection_requires_reason_records_it_and_releases_room(self):
        booking = self.pending()
        for reason in ("", "   ", "x" * 501):
            with self.subTest(reason=reason), self.assertRaises(BookingError):
                self.reject(booking, reason)
        booking = self.reject(booking, "  Please choose another room  ")
        self.assertEqual(booking.status, Reservation.Status.REJECTED)
        self.assertEqual(booking.rejection_reason, "Please choose another room")
        self.assertEqual(booking.rejected_by, self.staff)
        self.assertEqual(booking.rejected_at, NOW)
        notice = Notification.objects.get(event_type="rejection", recipient_email=self.employee.email)
        self.assertIn(booking.rejection_reason, notice.body)
        self.assertEqual(self.pending().status, Reservation.Status.PENDING)

    def test_cancelled_rejected_and_approved_cannot_be_approved_or_rejected_again(self):
        booking = self.pending()
        for status in (
            Reservation.Status.REJECTED,
            Reservation.Status.CANCELLED,
            Reservation.Status.APPROVED,
        ):
            if status == Reservation.Status.REJECTED:
                self.reject(booking)
            elif status == Reservation.Status.CANCELLED:
                booking = self.pending()
                cancel_booking(booking.pk, actor=self.employee)
            else:
                booking = self.approve(self.pending())
            with self.subTest(status=status):
                with self.assertRaises(BookingError):
                    self.approve(booking)
                with self.assertRaises(BookingError):
                    self.reject(booking)

    def test_employee_approved_edit_requeues_and_invalidates_previous_jobs_and_links(self):
        booking = self.approve(self.pending())
        send_due_notifications()
        token = EmailToken.objects.get(purpose="check_in", reservation=booking)
        queue_due_reminders(now=booking.starts_at - timedelta(minutes=45))
        booking = update_booking(
            booking.pk,
            booking_values(self.room, title="Revised plan", start_time=time(13), end_time=time(14)),
            actor=self.employee,
        )
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertIsNone(booking.approved_by)
        self.assertIsNone(booking.approved_at)
        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)
        self.assertFalse(
            Notification.objects.filter(reservation=booking, event_type="reminder", status="pending").exists()
        )
        self.assertEqual(queue_due_reminders(now=booking.starts_at - timedelta(minutes=45)), 0)
        mail.outbox.clear()
        self.assertEqual(send_due_notifications(), 2)
        self.assertTrue(all("awaiting administrator approval" in message.subject for message in mail.outbox))
        self.assertTrue(all("/check-in/link/" not in message.body for message in mail.outbox))

    def test_unchanged_edit_preserves_approval_and_staff_edit_preserves_reviewed_status(self):
        booking = self.approve(self.pending())
        revision = booking.revision
        booking = update_booking(booking.pk, booking_values(self.room), actor=self.employee)
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertEqual(booking.revision, revision)
        booking = update_booking(
            booking.pk,
            booking_values(self.room, description="Staff correction"),
            actor=self.staff,
            staff=True,
        )
        self.assertEqual(booking.status, Reservation.Status.APPROVED)
        self.assertEqual(booking.revision, revision + 1)

    def test_pending_meetings_cannot_check_in_or_receive_reminders(self):
        booking = self.pending()
        raw = "pending-checkin-must-fail"
        EmailToken.objects.create(
            user=self.employee,
            reservation=booking,
            email=self.employee.email,
            purpose="check_in",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=booking.starts_at + timedelta(minutes=15),
        )
        with patch("django.utils.timezone.now", return_value=booking.starts_at + timedelta(minutes=1)):
            with self.assertRaises(CheckInError):
                confirm_checkin(raw)
            with self.assertRaises(CheckInError):
                manual_checkin(booking.pk, actor=self.staff)
        self.assertEqual(queue_due_reminders(now=booking.starts_at - timedelta(minutes=30)), 0)

    def test_deactivated_organizer_cannot_use_existing_checkin_link(self):
        booking = self.approve(self.pending())
        raw = "disabled-organizer-checkin"
        EmailToken.objects.create(
            user=self.employee,
            reservation=booking,
            email=self.employee.email,
            purpose="check_in",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=booking.starts_at + timedelta(minutes=15),
        )
        User.objects.filter(pk=self.employee.pk).update(is_active=False)
        with patch("django.utils.timezone.now", return_value=booking.starts_at + timedelta(minutes=1)):
            with self.assertRaises(CheckInError):
                confirm_checkin(raw)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.APPROVED)

    def test_overdue_request_expires_as_cancelled_and_never_no_show(self):
        booking = self.pending()
        with patch("django.utils.timezone.now", return_value=booking.starts_at):
            with self.assertRaises(BookingError):
                self.approve(booking)
        self.assertEqual(release_due_pending_requests(now=booking.starts_at), 1)
        self.assertEqual(release_due_pending_requests(now=booking.starts_at), 0)
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.CANCELLED)
        self.assertIn("Approval window expired", booking.cancellation_reason)
        self.assertTrue(
            AuditEvent.objects.filter(action="booking_request_expired", target_id=booking.pk).exists()
        )
        self.assertFalse(AuditEvent.objects.filter(action="booking_no_show").exists())
        self.assertIn(
            booking.cancellation_reason,
            Notification.objects.get(event_type="cancellation", recipient_email=self.employee.email).body,
        )

    def test_reapproved_same_time_receives_a_fresh_reminder_for_current_revision(self):
        booking = self.approve(self.pending())
        at = booking.starts_at - timedelta(minutes=30)
        self.assertEqual(queue_due_reminders(now=at), 3)
        booking = update_booking(
            booking.pk, booking_values(self.room, title="Revised agenda"), actor=self.employee
        )
        booking = self.approve(booking)
        self.assertEqual(queue_due_reminders(now=at), 3)
        self.assertEqual(
            Notification.objects.filter(
                event_type="reminder", reservation_revision=booking.revision, status="pending"
            ).count(),
            3,
        )
        self.assertEqual(queue_due_reminders(now=at), 0)

    def test_retry_failed_mail_respects_request_decision_and_revision(self):
        booking = self.pending()
        request_job = Notification.objects.get(event_type="request", recipient_email=self.employee.email)
        Notification.objects.filter(pk=request_job.pk).update(status="failed")
        self.assertEqual(retry_failed_mail(request_job.pk), (1, 0))
        booking = self.approve(booking)
        confirmation = Notification.objects.get(
            event_type="confirmation", recipient_email=self.employee.email
        )
        Notification.objects.filter(pk=confirmation.pk).update(status="failed")
        self.assertEqual(retry_failed_mail(confirmation.pk), (1, 0))
        update_booking(
            booking.pk, booking_values(self.room, title="Needs another review"), actor=self.employee
        )
        Notification.objects.filter(pk=confirmation.pk).update(status="failed")
        self.assertEqual(retry_failed_mail(confirmation.pk), (0, 1))
        booking = self.reject(booking)
        rejection = Notification.objects.get(event_type="rejection", recipient_email=self.employee.email)
        Notification.objects.filter(pk=rejection.pk).update(status="failed")
        self.assertEqual(retry_failed_mail(rejection.pk), (1, 0))

    def test_pending_cancellation_releases_held_time(self):
        booking = self.pending()
        cancel_booking(booking.pk, actor=self.employee, reason="No longer needed")
        self.assertEqual(self.pending().status, Reservation.Status.PENDING)
        self.assertTrue(
            Notification.objects.filter(event_type="cancellation", recipient_email=self.staff.email).exists()
        )

    def test_stale_confirmation_is_skipped_even_if_retried_after_requeue(self):
        booking = self.approve(self.pending())
        old = Notification.objects.get(event_type="confirmation", recipient_email=self.employee.email)
        update_booking(
            booking.pk, booking_values(self.room, description="Changed agenda"), actor=self.employee
        )
        Notification.objects.filter(pk=old.pk).update(status="failed", next_attempt_at=NOW)
        send_due_notifications()
        old.refresh_from_db()
        self.assertEqual(old.status, Notification.Status.SKIPPED)
        self.assertTrue(all("approved" not in message.subject for message in mail.outbox))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class ApprovalConcurrencyTests(TransactionTestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.employee = User.objects.create_user("employee@transgate.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Approval room", location="WDN", floor="2", capacity=8)
        self.booking = create_booking(booking_values(self.room), actor=self.employee)[0]

    def parallel(self, functions):
        barrier = Barrier(len(functions))

        def run(function):
            close_old_connections()
            try:
                barrier.wait(timeout=15)
                function()
                return "success"
            except BookingError:
                return "closed"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(functions)) as pool:
            futures = [pool.submit(run, function) for function in functions]
            return [future.result(timeout=30) for future in futures]

    def test_two_approvals_commit_one_decision_and_confirmation_set(self):
        results = self.parallel(
            [
                lambda: approve_booking(self.booking.pk, actor=self.staff, request=staff_request(self.staff)),
                lambda: approve_booking(self.booking.pk, actor=self.staff, request=staff_request(self.staff)),
            ]
        )
        self.assertCountEqual(results, ["success", "closed"])
        self.assertEqual(AuditEvent.objects.filter(action="booking_approved").count(), 1)
        self.assertEqual(Notification.objects.filter(event_type="confirmation").count(), 3)

    def test_organizer_deactivation_commits_before_waiting_approval_is_denied(self):
        from threading import Event

        locked, waiting = Event(), Event()

        def deactivate():
            close_old_connections()
            try:
                with transaction.atomic():
                    user = User.objects.select_for_update(no_key=True).get(pk=self.employee.pk)
                    locked.set()
                    if not waiting.wait(timeout=10):
                        raise TimeoutError("Approval did not start")
                    user.is_active = False
                    user.save(update_fields=["is_active"])
                return "deactivated"
            finally:
                connections.close_all()

        def approve():
            close_old_connections()
            try:
                if not locked.wait(timeout=10):
                    raise TimeoutError("Deactivation did not lock the organizer")
                waiting.set()
                try:
                    approve_booking(self.booking.pk, actor=self.staff, request=staff_request(self.staff))
                    return "approved"
                except BookingError:
                    return "denied"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(deactivate)
            second = pool.submit(approve)
            self.assertEqual(first.result(timeout=20), "deactivated")
            self.assertEqual(second.result(timeout=20), "denied")
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.PENDING)
        self.assertFalse(AuditEvent.objects.filter(action="booking_approved").exists())

    def test_approve_and_reject_race_commits_one_terminal_decision(self):
        results = self.parallel(
            [
                lambda: approve_booking(self.booking.pk, actor=self.staff, request=staff_request(self.staff)),
                lambda: reject_booking(
                    self.booking.pk, actor=self.staff, request=staff_request(self.staff), reason="Room needed"
                ),
            ]
        )
        self.assertCountEqual(results, ["success", "closed"])
        self.booking.refresh_from_db()
        self.assertIn(self.booking.status, [Reservation.Status.APPROVED, Reservation.Status.REJECTED])
        self.assertEqual(
            AuditEvent.objects.filter(action__in=["booking_approved", "booking_rejected"]).count(), 1
        )


class ApprovalMigrationTests(TransactionTestCase):
    migrate_from = [("booking", "0007_notification_leases_worker_heartbeat")]
    migrate_to = [("booking", "0008_booking_approval")]

    def test_existing_confirmed_booking_and_notification_are_preserved(self):
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(self.migrate_to))
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_from)
        old = executor.loader.project_state(self.migrate_from).apps
        old_user = old.get_model("booking", "User").objects.create(email="legacy@wdn.com.np", password="!")
        room = old.get_model("booking", "Room").objects.create(
            name="Legacy room", location="WDN", floor="1", capacity=8
        )
        starts = NOW + timedelta(days=1, hours=3)
        ends = starts + timedelta(hours=1)
        booking = old.get_model("booking", "Reservation").objects.create(
            room_id=room.pk,
            organizer_id=old_user.pk,
            created_by_id=old_user.pk,
            kind="booking",
            status="confirmed",
            starts_at=starts,
            ends_at=ends,
            occupied_from=starts,
            occupied_until=ends + timedelta(minutes=15),
            title="Legacy confirmed",
        )
        notification = old.get_model("booking", "Notification").objects.create(
            reservation_id=booking.pk,
            recipient_email=old_user.email,
            event_type="confirmation",
            subject="Existing confirmation",
            body="Existing meeting",
            next_attempt_at=NOW,
        )
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        current = executor.loader.project_state(self.migrate_to).apps
        migrated = current.get_model("booking", "Reservation").objects.get(pk=booking.pk)
        self.assertEqual(migrated.status, "approved")
        self.assertEqual(migrated.title, "Legacy confirmed")
        self.assertEqual(migrated.organizer_id, old_user.pk)
        self.assertIsNone(migrated.approved_by_id)
        self.assertIsNone(migrated.approved_at)
        self.assertEqual(
            current.get_model("booking", "Notification").objects.get(pk=notification.pk).reservation_revision,
            1,
        )
        with self.assertRaises(IntegrityError), transaction.atomic():
            current.get_model("booking", "Reservation").objects.create(
                room_id=room.pk,
                organizer_id=old_user.pk,
                created_by_id=old_user.pk,
                kind="booking",
                status="pending",
                starts_at=starts,
                ends_at=ends,
                occupied_from=starts,
                occupied_until=ends,
                title="Conflicting pending request",
            )
        with self.assertRaises(IntegrityError), transaction.atomic():
            current.get_model("booking", "Reservation").objects.filter(pk=booking.pk).update(
                status="confirmed"
            )

    def test_rollback_releases_unapproved_requests_and_supersedes_new_event_jobs(self):
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(self.migrate_to))
        executor = MigrationExecutor(connection)
        current = executor.loader.project_state(self.migrate_to).apps
        users = current.get_model("booking", "User")
        reservations = current.get_model("booking", "Reservation")
        notifications = current.get_model("booking", "Notification")
        user = users.objects.create(email="rollback@wdn.com.np", password="!")
        room = current.get_model("booking", "Room").objects.create(
            name="Rollback room", location="WDN", floor="1", capacity=8
        )
        booking_ids = {}
        jobs = []
        for index, status in enumerate(("approved", "pending", "rejected")):
            starts = NOW + timedelta(days=1, hours=index * 3)
            booking = reservations.objects.create(
                room_id=room.pk,
                organizer_id=user.pk,
                created_by_id=user.pk,
                kind="booking",
                status=status,
                starts_at=starts,
                ends_at=starts + timedelta(hours=1),
                occupied_from=starts,
                occupied_until=starts + timedelta(hours=1, minutes=15),
                title=f"Rollback {status}",
                rejection_reason="Not required" if status == "rejected" else "",
                rejected_at=NOW if status == "rejected" else None,
            )
            booking_ids[status] = booking.pk
            if status != "approved":
                for job_status in ("pending", "failed", "sending", "sent"):
                    event = "request" if status == "pending" else "rejection"
                    job = notifications.objects.create(
                        reservation_id=booking.pk,
                        reservation_revision=1,
                        recipient_email=user.email,
                        event_type=event,
                        subject="Rollback approval event",
                        body="Original event",
                        status=job_status,
                        next_attempt_at=NOW,
                        lease_token=uuid.uuid4() if job_status == "sending" else None,
                        lease_expires_at=NOW + timedelta(minutes=5) if job_status == "sending" else None,
                    )
                    jobs.append((job.pk, job_status))
        confirmation = notifications.objects.create(
            reservation_id=booking_ids["approved"],
            reservation_revision=1,
            recipient_email=user.email,
            event_type="confirmation",
            subject="Approved meeting",
            body="Approved meeting",
            next_attempt_at=NOW,
        )
        executor.migrate(self.migrate_from)
        old = executor.loader.project_state(self.migrate_from).apps
        old_reservations = old.get_model("booking", "Reservation")
        old_notifications = old.get_model("booking", "Notification")
        self.assertEqual(old_reservations.objects.get(pk=booking_ids["approved"]).status, "confirmed")
        for status in ("pending", "rejected"):
            restored = old_reservations.objects.get(pk=booking_ids[status])
            self.assertEqual(restored.status, "cancelled")
            self.assertIsNotNone(restored.cancelled_at)
        for job_id, previous in jobs:
            restored = old_notifications.objects.get(pk=job_id)
            self.assertEqual(restored.status, "sent" if previous == "sent" else "skipped")
            self.assertIsNone(restored.lease_token)
            self.assertIsNone(restored.lease_expires_at)
        self.assertEqual(old_notifications.objects.get(pk=confirmation.pk).status, "pending")
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        self.assertEqual(
            Reservation.objects.get(pk=booking_ids["approved"]).status, Reservation.Status.APPROVED
        )
        self.assertEqual(Reservation.objects.filter(status=Reservation.Status.CANCELLED).count(), 2)
        self.assertEqual(
            Notification.objects.filter(event_type__in=["request", "rejection"], status="skipped").count(), 6
        )
