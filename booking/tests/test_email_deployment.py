import hashlib
import os
import re
import runpy
import socketserver
import threading
import uuid
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from booking.health import readiness, worker_is_healthy
from booking.mail_backends import DisabledEmailBackend, MailUnavailable
from booking.models import EmailToken, Notification, Reservation, Room, User, WorkerHeartbeat
from booking.services.checkin import release_due_no_shows
from booking.services.mail_delivery import deliver_mail
from booking.services.notifications import queue_booking_event, send_due_notifications


class EmailConfigurationTests(SimpleTestCase):
    def configuration(self, **changes):
        env = {
            "DJANGO_SECRET_KEY": "x" * 70,
            "DJANGO_ALLOWED_HOSTS": "localhost",
            "DJANGO_PUBLIC_BASE_URL": "http://localhost",
            "POSTGRES_DB": "test",
            "POSTGRES_USER": "test",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_HOST": "db",
        }
        env.update(changes)
        with patch.dict(os.environ, env, clear=True):
            return runpy.run_path(str(Path(settings.BASE_DIR) / "config" / "settings.py"))

    def test_unconfigured_smtp_starts_with_warning_and_disabled_backend(self):
        with self.assertLogs("booking.configuration", level="WARNING"):
            configured = self.configuration(DJANGO_EMAIL_BACKEND="smtp")
        self.assertFalse(configured["EMAIL_READY"])
        self.assertEqual(configured["EMAIL_BACKEND"], "booking.mail_backends.DisabledEmailBackend")
        with self.assertRaises(MailUnavailable):
            DisabledEmailBackend().send_messages([object()])

    def test_configured_smtp_supports_starttls_or_implicit_ssl(self):
        configured = self.configuration(
            DJANGO_EMAIL_BACKEND="smtp", SMTP_HOST="relay.invalid", DJANGO_FROM_EMAIL="rooms@wdn.com.np"
        )
        self.assertTrue(configured["EMAIL_READY"])
        self.assertTrue(configured["EMAIL_USE_TLS"])
        configured = self.configuration(
            DJANGO_EMAIL_BACKEND="smtp",
            SMTP_HOST="relay.invalid",
            DJANGO_FROM_EMAIL="rooms@wdn.com.np",
            SMTP_USE_TLS="false",
            SMTP_USE_SSL="true",
            SMTP_PORT="465",
        )
        self.assertTrue(configured["EMAIL_USE_SSL"])
        with self.assertRaises(RuntimeError):
            self.configuration(DJANGO_EMAIL_BACKEND="smtp", SMTP_USE_TLS="true", SMTP_USE_SSL="true")

    def test_https_requires_matching_https_origin_and_blocks_file_email(self):
        with self.assertRaises(RuntimeError):
            self.configuration(DJANGO_HTTPS="true")
        with self.assertRaises(RuntimeError):
            self.configuration(DJANGO_PUBLIC_BASE_URL="https://unapproved.invalid")
        with self.assertRaises(RuntimeError):
            self.configuration(
                DJANGO_HTTPS="true", DJANGO_PUBLIC_BASE_URL="https://localhost", DJANGO_EMAIL_BACKEND="file"
            )

    def test_zero_delivery_is_failure(self):
        with patch("booking.services.mail_delivery.send_mail", return_value=0):
            with self.assertRaises(RuntimeError):
                deliver_mail("subject", "body", ["person@wdn.com.np"])

    def test_real_smtp_backend_delivers_to_local_test_relay(self):
        messages = []

        class Relay(socketserver.StreamRequestHandler):
            def handle(self):
                self.wfile.write(b"220 local-test-relay\r\n")
                while line := self.rfile.readline():
                    command = line.upper()
                    if command.startswith(b"DATA"):
                        self.wfile.write(b"354 Send message\r\n")
                        message = []
                        while (body_line := self.rfile.readline()) not in {b".\r\n", b""}:
                            message.append(body_line)
                        messages.append(b"".join(message))
                        self.wfile.write(b"250 Accepted\r\n")
                    elif command.startswith(b"QUIT"):
                        self.wfile.write(b"221 Closing\r\n")
                        return
                    else:
                        self.wfile.write(b"250 OK\r\n")

        with socketserver.TCPServer(("127.0.0.1", 0), Relay) as relay:
            thread = threading.Thread(target=relay.serve_forever, daemon=True)
            thread.start()
            try:
                with override_settings(
                    EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                    EMAIL_HOST="127.0.0.1",
                    EMAIL_PORT=relay.server_address[1],
                    EMAIL_USE_TLS=False,
                    EMAIL_USE_SSL=False,
                    EMAIL_HOST_USER="",
                    EMAIL_HOST_PASSWORD="",
                    EMAIL_TIMEOUT=2,
                    DEFAULT_FROM_EMAIL="rooms@local.invalid",
                ):
                    self.assertEqual(
                        deliver_mail("SMTP test", "Local test message", ["person@local.invalid"]), 1
                    )
                self.assertEqual(len(messages), 1)
                self.assertIn(b"Subject: SMTP test", messages[0])
                self.assertIn(b"Local test message", messages[0])
            finally:
                relay.shutdown()
                thread.join(timeout=2)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class NotificationDeliveryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("organizer@wdn.com.np")
        self.room = Room.objects.create(name="Delivery test room", location="WDN", floor="2", capacity=10)
        self.now = timezone.now()
        start = self.now + timedelta(minutes=30)
        end = start + timedelta(hours=1)
        self.booking = Reservation.objects.create(
            room=self.room,
            organizer=self.user,
            created_by=self.user,
            kind="booking",
            status="confirmed",
            title="A" * 200,
            starts_at=start,
            ends_at=end,
            occupied_from=start,
            occupied_until=end + timedelta(minutes=15),
        )

    def notification(self, **changes):
        data = {
            "reservation": self.booking,
            "recipient_email": self.user.email,
            "event_type": "reminder",
            "subject": "Reminder",
            "body": f"start={self.booking.starts_at.isoformat()}",
            "next_attempt_at": self.now,
        }
        data.update(changes)
        return Notification.objects.create(**data)

    def test_confirmation_has_checkin_link_and_bounded_subject(self):
        queue_booking_event(self.booking, "confirmation")
        notification = Notification.objects.get()
        self.assertLessEqual(len(notification.subject), 240)
        self.assertEqual(send_due_notifications(), 1)
        raw = re.search(r"/check-in/link/([^/]+)/", mail.outbox[0].body).group(1)
        self.assertTrue(
            EmailToken.objects.filter(
                token_hash=hashlib.sha256(raw.encode()).hexdigest(), purpose="check_in"
            ).exists()
        )

    def test_newline_title_is_safe_in_email_header_and_preserved_in_body(self):
        self.booking.title = "Weekly\nplanning"
        self.booking.save(update_fields=["title"])
        queue_booking_event(self.booking, "confirmation")
        self.assertEqual(send_due_notifications(), 1)
        self.assertIn("Weekly planning", mail.outbox[0].subject)
        self.assertNotIn("\n", mail.outbox[0].subject)
        self.assertIn(self.booking.title, mail.outbox[0].body)

    def test_long_title_no_show_releases_reservation_and_bounds_email_subject(self):
        self.assertEqual(release_due_no_shows(now=self.booking.starts_at + timedelta(minutes=16)), 1)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "no_show")
        self.assertTrue(
            all(len(job.subject) <= 240 for job in Notification.objects.filter(event_type="no_show"))
        )

    def test_reminder_recovery_during_checkin_window(self):
        notification = self.notification()
        recovered_at = self.booking.starts_at + timedelta(minutes=5)
        with patch("booking.services.notifications.timezone.now", return_value=recovered_at):
            self.assertEqual(send_due_notifications(now=recovered_at), 1)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "sent")
        self.assertIn("/check-in/link/", mail.outbox[0].body)

    def test_superseded_reminder_is_skipped_without_fake_delivery(self):
        notification = self.notification()
        self.booking.status = "cancelled"
        self.booking.save(update_fields=["status"])
        self.assertEqual(send_due_notifications(), 0)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "skipped")
        self.assertIsNone(notification.sent_at)
        self.assertEqual(len(mail.outbox), 0)

    def test_zero_delivery_is_recorded_as_failed(self):
        notification = self.notification(event_type="confirmation", body="Confirmed")
        with patch("booking.services.mail_delivery.send_mail", return_value=0):
            self.assertEqual(send_due_notifications(), 0)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "failed")
        self.assertIsNone(notification.sent_at)
        self.assertEqual(notification.last_error, "RuntimeError")

    @override_settings(EMAIL_BACKEND="booking.mail_backends.DisabledEmailBackend")
    def test_disabled_delivery_preserves_pending_message_without_exhausting_retries(self):
        notification = self.notification()
        self.assertEqual(send_due_notifications(), 0)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "pending")
        self.assertEqual(notification.attempts, 0)

    def test_expired_final_claim_is_visible_failure(self):
        notification = self.notification(
            status="sending",
            attempts=5,
            lease_token=uuid.uuid4(),
            lease_expires_at=self.now - timedelta(minutes=1),
        )
        self.assertEqual(send_due_notifications(), 0)
        notification.refresh_from_db()
        self.assertEqual(notification.status, "failed")
        self.assertEqual(notification.last_error, "WorkerInterrupted")
        self.assertIsNone(notification.lease_token)

    def test_expired_claim_recovers_and_current_claim_is_not_taken(self):
        active = self.notification(
            status="sending",
            attempts=1,
            lease_token=uuid.uuid4(),
            lease_expires_at=self.now + timedelta(minutes=5),
        )
        expired = self.notification(
            status="sending",
            attempts=4,
            lease_token=uuid.uuid4(),
            lease_expires_at=self.now - timedelta(minutes=1),
        )
        self.assertEqual(send_due_notifications(), 1)
        active.refresh_from_db()
        expired.refresh_from_db()
        self.assertEqual(active.status, "sending")
        self.assertEqual(expired.status, "sent")
        self.assertEqual(expired.attempts, 5)
        self.assertIsNone(expired.lease_token)

    def test_failed_mail_retry_requeues_only_current_booking_events(self):
        current = self.notification(status="failed", attempts=5)
        obsolete = self.notification(status="failed", attempts=5, body="start=old-date")
        call_command("retry_failed_mail", all=True)
        current.refresh_from_db()
        obsolete.refresh_from_db()
        self.assertEqual(current.status, "pending")
        self.assertEqual(current.attempts, 0)
        self.assertEqual(obsolete.status, "skipped")


class WorkerHealthTests(TestCase):
    def test_freshness_and_readiness(self):
        request = RequestFactory().get("/healthz/")
        self.assertFalse(worker_is_healthy())
        self.assertEqual(readiness(request).status_code, 503)
        WorkerHeartbeat.objects.create(last_success_at=timezone.now())
        self.assertTrue(worker_is_healthy())
        self.assertEqual(readiness(request).status_code, 200)
        WorkerHeartbeat.objects.update(last_success_at=timezone.now() - timedelta(minutes=3))
        self.assertEqual(readiness(request).status_code, 503)

    def test_worker_once_records_reconciliation(self):
        with (
            patch("booking.management.commands.run_booking_worker.close_old_connections"),
            patch("booking.management.commands.run_booking_worker.release_due_no_shows", return_value=0),
            patch("booking.management.commands.run_booking_worker.complete_finished", return_value=0),
            patch("booking.management.commands.run_booking_worker.queue_due_reminders", return_value=0),
            patch("booking.management.commands.run_booking_worker.send_due_notifications", return_value=0),
        ):
            call_command("run_booking_worker", once=True)
        self.assertTrue(worker_is_healthy())


class InitialSetupTests(TestCase):
    @override_settings(HTTPS_ENABLED=False, MAIL_MODE="file")
    def test_demo_seed_is_safe_and_repeat_refuses_to_overwrite(self):
        call_command("seed_demo_rooms", verbosity=0)
        self.assertEqual(Room.objects.count(), 5)
        with self.assertRaises(CommandError):
            call_command("seed_demo_rooms", verbosity=0)
        self.assertEqual(Room.objects.count(), 5)

    @override_settings(HTTPS_ENABLED=True, MAIL_MODE="disabled")
    def test_production_demo_seed_is_rejected(self):
        with self.assertRaises(CommandError):
            call_command("seed_demo_rooms", verbosity=0)
        self.assertEqual(Room.objects.count(), 0)

    @override_settings(EMAIL_BACKEND="booking.mail_backends.DisabledEmailBackend", MAIL_MODE="disabled")
    def test_initial_staff_failure_is_explicit_without_duplicate_account(self):
        for _ in range(2):
            with self.assertRaisesMessage(CommandError, "setup email failed"):
                call_command("create_staff_account", "desk@wdn.com.np")
        user = User.objects.get(email="desk@wdn.com.np")
        self.assertTrue(user.is_staff)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(User.objects.filter(email="desk@wdn.com.np").count(), 1)
