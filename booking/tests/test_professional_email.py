import hashlib
import io
import re
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib.sessions.backends.db import SessionStore
from django.core import mail
from django.core.management import call_command
from django.test import RequestFactory, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from PIL import Image

from booking.models import (
    BookingAttendee,
    BookingPolicy,
    EmailToken,
    Notification,
    Reservation,
    Room,
    User,
)
from booking.services.bookings import update_booking
from booking.services.email_login import request_login_link
from booking.services.email_templates import EMAIL_LOGO_CID, render_email
from booking.services.mail_delivery import deliver_mail
from booking.services.notifications import (
    queue_booking_event,
    queue_conflict_notice,
    queue_due_reminders,
    send_due_notifications,
)
from booking.services.staff_auth import start_staff_login

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 8, 9, 0, tzinfo=LOCAL_TZ)
PUBLIC_ORIGIN = "https://rooms.wdn.com.np"


def html_part(message):
    return next(content for content, mimetype in message.alternatives if mimetype == "text/html")


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class BrandedEmailDeliveryTests(SimpleTestCase):
    def test_html_mime_contains_plain_fallback_and_inline_original_logo(self):
        html = render_email(heading="Ready", intro="Meeting details", status="Confirmed")
        self.assertEqual(
            deliver_mail("Safe\nsubject", "Plain details", ["employee@wdn.com.np"], html_body=html), 1
        )
        message = mail.outbox[0]
        self.assertEqual(message.subject, "Safe subject")
        self.assertEqual(message.body, "Plain details")
        self.assertEqual(message.alternatives[0].mimetype, "text/html")
        mime = message.message()
        self.assertEqual(mime.get_content_type(), "multipart/related")
        parts = list(mime.walk())
        self.assertEqual(sum(part.get_content_type() == "text/plain" for part in parts), 1)
        self.assertEqual(sum(part.get_content_type() == "text/html" for part in parts), 1)
        image = next(part for part in parts if part.get_content_type() == "image/png")
        self.assertEqual(image["Content-ID"], f"<{EMAIL_LOGO_CID}>")
        self.assertEqual(image.get_content_disposition(), "inline")
        self.assertEqual(
            image.get_payload(decode=True),
            (Path(settings.BASE_DIR) / "booking/static/booking/transgate-email-logo.png").read_bytes(),
        )
        with Image.open(io.BytesIO(image.get_payload(decode=True))) as logo:
            self.assertEqual(logo.size, (876, 86))
        self.assertIn(f'src="cid:{EMAIL_LOGO_CID}"', html)
        self.assertNotIn("<script", html)
        self.assertNotIn("<form", html)
        self.assertNotRegex(html, r'<img[^>]+src="https?://')

    def test_plain_operational_email_retains_legacy_backend_contract(self):
        with patch("booking.services.mail_delivery.send_mail", return_value=1) as sender:
            self.assertEqual(deliver_mail("One\r\ntwo", "Plain message", ["it@wdn.com.np"]), 1)
        sender.assert_called_once_with(
            "One two", "Plain message", settings.DEFAULT_FROM_EMAIL, ["it@wdn.com.np"], fail_silently=False
        )

    def test_html_backend_zero_delivery_or_exception_is_not_success(self):
        for error in (None, OSError("unavailable")):
            with self.subTest(error=error):
                with patch(
                    "booking.services.mail_delivery.EmailMultiAlternatives.send",
                    return_value=0,
                    side_effect=error,
                ):
                    with self.assertRaises((RuntimeError, OSError)):
                        deliver_mail("Title", "Plain", ["it@wdn.com.np"], html_body="<p>HTML</p>")

    def test_shared_renderer_escapes_user_text_and_attributes(self):
        payload = '<img src=x onerror="alert(1)"> & quoted'
        html = render_email(
            heading=payload,
            intro=payload,
            metadata=[{"label": "Meeting", "value": payload}],
            paragraphs=[payload],
            action_url=f'{PUBLIC_ORIGIN}/?test="unsafe"&value=1',
            action_label=payload,
            notice=payload,
        )
        self.assertNotIn(payload, html)
        self.assertIn("&lt;img src=x onerror=&quot;alert(1)&quot;&gt; &amp; quoted", html)
        self.assertIn("?test=&quot;unsafe&quot;&amp;value=1", html)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", PUBLIC_BASE_URL=PUBLIC_ORIGIN
)
class AuthenticationEmailPresentationTests(TestCase):
    def request(self):
        request = RequestFactory().post("/sign-in/", REMOTE_ADDR="192.0.2.20")
        request.session = SessionStore()
        return request

    def test_employee_signin_html_and_plain_use_same_one_time_link(self):
        self.assertTrue(request_login_link("employee@wdn.com.np", self.request()))
        message = mail.outbox[-1]
        link = re.search(r"https?://\S+/sign-in/link/\S+", message.body).group()
        self.assertTrue(link.startswith(PUBLIC_ORIGIN))
        html = html_part(message)
        self.assertIn(f'href="{link}"', html)
        self.assertIn("Sign in to Meeting Rooms", html)
        self.assertIn("15 minutes", html)
        self.assertNotIn(EmailToken.objects.get().token_hash, html)

    def test_staff_code_has_same_code_and_expiry_in_both_parts(self):
        user = User.objects.create_user(
            "desk@wdn.com.np", password="Presentation test credential", is_staff=True
        )
        self.assertTrue(start_staff_login(user.email, "Presentation test credential", self.request()))
        message = mail.outbox[-1]
        code = re.search(r"\b\d{8}\b", message.body).group()
        self.assertIn(code, html_part(message))
        self.assertIn("10 minutes", html_part(message))
        self.assertNotIn("Check in</a>", html_part(message))

    def test_bootstrap_setup_email_has_matching_button_and_plain_link(self):
        call_command("create_staff_account", "new.desk@transgate.com.np", stdout=io.StringIO())
        message = mail.outbox[-1]
        link = re.search(r"https?://\S+/staff/set-password/\S+", message.body).group()
        self.assertIn(f'href="{link}"', html_part(message))
        self.assertIn("Set your staff password", html_part(message))


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", PUBLIC_BASE_URL=PUBLIC_ORIGIN
)
class BookingEmailPresentationTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        self.organizer = User.objects.create_user(
            "organizer@wdn.com.np", first_name="Office", last_name="Organizer"
        )
        self.attendee = User.objects.create_user("attendee@transgate.com.np")
        self.room = Room.objects.create(
            name="Boardroom", location="Kantipath", floor="3", capacity=10, requires_approval=False
        )
        self.start = NOW + timedelta(minutes=30)
        self.booking = Reservation.objects.create(
            room=self.room,
            organizer=self.organizer,
            created_by=self.organizer,
            kind=Reservation.Kind.BOOKING,
            status=Reservation.Status.APPROVED,
            title='<script>alert("meeting")</script> planning',
            description="Planning & decisions <img src=x>",
            department="Operations",
            starts_at=self.start,
            ends_at=self.start + timedelta(hours=1),
            occupied_from=self.start,
            occupied_until=self.start + timedelta(hours=1, minutes=15),
            approved_at=NOW,
        )
        BookingAttendee.objects.create(reservation=self.booking, email=self.attendee.email)

    def organizer_mail(self):
        return next(message for message in mail.outbox if message.to == [self.organizer.email])

    def test_confirmation_has_escaped_details_exact_window_and_organizer_only_button(self):
        BookingPolicy.objects.update(check_in_minutes=10)
        queue_booking_event(self.booking, "confirmation")
        self.assertEqual(send_due_notifications(), 2)
        message = self.organizer_mail()
        html = html_part(message)
        raw = re.search(r"/check-in/link/([^/]+)/", message.body).group(1)
        link = PUBLIC_ORIGIN + reverse("checkin-link", args=[raw])
        self.assertIn(f'href="{link}"', html)
        self.assertIn("&#10003; Check in", html)
        self.assertIn("between 09:30 and 09:40 Nepal time", html)
        self.assertIn("Thursday, 08 October 2026", html)
        self.assertIn("09:30 – 10:30 Nepal time", html)
        self.assertIn("Floor 3", html)
        self.assertIn("Automatic", html)
        self.assertNotIn(self.booking.title, html)
        self.assertIn("&lt;script&gt;alert(&quot;meeting&quot;)&lt;/script&gt; planning", html)
        self.assertIn("Planning &amp; decisions &lt;img src=x&gt;", html)
        self.assertIn(self.booking.title, message.body)
        self.assertIn(PUBLIC_ORIGIN + reverse("booking-detail", args=[self.booking.pk]), html)
        attendee_message = next(item for item in mail.outbox if item.to == [self.attendee.email])
        self.assertNotIn("/check-in/link/", html_part(attendee_message))
        self.assertNotIn("/check-in/link/", attendee_message.body)
        self.assertIn("View meeting", html_part(attendee_message))
        self.assertIn("organizer manages", html_part(attendee_message))
        token = EmailToken.objects.get(purpose=EmailToken.Purpose.CHECK_IN)
        self.assertEqual(token.token_hash, hashlib.sha256(raw.encode()).hexdigest())
        self.assertEqual(token.expires_at, self.start + timedelta(minutes=10))

    def test_email_checkin_button_get_does_not_consume_and_confirmation_post_does(self):
        queue_booking_event(self.booking, "confirmation")
        send_due_notifications()
        raw = re.search(r"/check-in/link/([^/]+)/", self.organizer_mail().body).group(1)
        at_start = patch("django.utils.timezone.now", return_value=self.start)
        with at_start:
            self.assertRedirects(
                self.client.get(reverse("checkin-link", args=[raw])), reverse("checkin-confirm")
            )
            self.booking.refresh_from_db()
            self.assertEqual(self.booking.status, Reservation.Status.APPROVED)
            self.assertIsNone(EmailToken.objects.get(purpose=EmailToken.Purpose.CHECK_IN).consumed_at)
            self.assertEqual(self.client.post(reverse("checkin-confirm")).status_code, 200)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, Reservation.Status.CHECKED_IN)

    def test_external_attendee_gets_contact_action_without_employee_login_or_checkin_promise(self):
        guest_email = "guest@outside.example"
        BookingAttendee.objects.create(reservation=self.booking, email=guest_email)
        for event in ("confirmation", "change", "reminder"):
            with self.subTest(event=event):
                mail.outbox.clear()
                if event == "reminder":
                    self.assertEqual(queue_due_reminders(), 3)
                else:
                    queue_booking_event(self.booking, event)
                self.assertEqual(send_due_notifications(), 3)
                message = next(item for item in mail.outbox if item.to == [guest_email])
                html = html_part(message)
                self.assertIn("Contact organizer", html)
                self.assertIn(f'href="mailto:{self.organizer.email}"', html)
                self.assertIn("Contact the organizer for meeting details or updates", html)
                self.assertNotIn("when you sign in with this company email", html)
                self.assertNotIn("View meeting", html)
                self.assertNotIn("/check-in/link/", html)
                self.assertNotIn("/check-in/link/", message.body)
                self.assertNotIn(
                    public_details := PUBLIC_ORIGIN + reverse("booking-detail", args=[self.booking.pk]), html
                )
                self.assertNotIn(public_details, message.body)
                self.assertIn(f"Contact organizer: {self.organizer.email}", message.body)
                self.assertFalse(User.objects.filter(email=guest_email).exists())

    def test_changed_meeting_notifies_removed_members_with_contact_action_and_current_members_with_view(self):
        staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        inactive_staff = User.objects.create_user("former.desk@wdn.com.np", is_staff=True, is_active=False)
        new_organizer = User.objects.create_user("new.organizer@wdn.com.np")
        BookingAttendee.objects.create(reservation=self.booking, email=inactive_staff.email)
        invited_email = "INVITED.EMPLOYEE@WDN.COM.NP"
        data = {
            "room": self.room,
            "organizer_email": new_organizer.email,
            "date": self.start.date(),
            "start_time": self.start.time(),
            "end_time": (self.start + timedelta(hours=1)).time(),
            "title": "Updated planning meeting",
            "description": "The meeting membership has changed",
            "meeting_type": Reservation.MeetingType.INTERNAL,
            "guest_company_name": "",
            "external_attendee_count": 0,
            "department": "Operations",
            "attendees": [invited_email],
            "refreshments_requested": False,
            "front_desk_notes": "",
        }
        self.booking = update_booking(self.booking.pk, data, actor=staff, staff=True)
        self.assertEqual(send_due_notifications(), 6)
        details_url = PUBLIC_ORIGIN + reverse("booking-detail", args=[self.booking.pk])
        for removed in (self.organizer, self.attendee, inactive_staff):
            message = next(item for item in mail.outbox if item.to == [removed.email])
            html = html_part(message)
            self.assertIn("changed", message.subject)
            self.assertIn(f'href="mailto:{new_organizer.email}"', html)
            self.assertIn("Contact organizer", html)
            self.assertIn(f"Contact organizer: {new_organizer.email}", message.body)
            self.assertNotIn("when you sign in with this company email", html)
            self.assertNotIn(details_url, html)
            self.assertNotIn(details_url, message.body)
            self.assertNotIn("/check-in/link/", html)
            self.assertNotIn("/check-in/link/", message.body)
        for email in (new_organizer.email, invited_email, staff.email):
            message = next(item for item in mail.outbox if item.to == [email])
            self.assertIn("View meeting", html_part(message))
            self.assertIn(details_url, html_part(message))
            self.assertIn(details_url, message.body)
            if email != new_organizer.email:
                self.assertNotIn("/check-in/link/", html_part(message))
        self.assertFalse(User.objects.filter(email__iexact=invited_email).exists())
        self.assertEqual(
            EmailToken.objects.get(purpose=EmailToken.Purpose.CHECK_IN).user_id, new_organizer.pk
        )

    def test_reminder_keeps_dedup_marker_and_has_checkin_button(self):
        self.assertEqual(queue_due_reminders(), 2)
        self.assertEqual(queue_due_reminders(), 0)
        # PostgreSQL reloads aware datetimes in UTC; the worker uses that canonical
        # database value, rather than the fixture's equivalent Nepal-time offset.
        self.booking.refresh_from_db(fields=["starts_at"])
        expected_marker = f"start={self.booking.starts_at.isoformat()}"
        reminders = Notification.objects.filter(reservation=self.booking, event_type="reminder")
        self.assertCountEqual(reminders.values_list("body", flat=True), [expected_marker, expected_marker])
        self.assertEqual(send_due_notifications(), 2)
        self.assertCountEqual(reminders.values_list("body", flat=True), [expected_marker, expected_marker])
        self.assertIn("&#10003; Check in", html_part(self.organizer_mail()))
        self.assertIn("Meeting reminder", html_part(self.organizer_mail()))

    def test_expired_checkin_is_never_offered_in_confirmation_or_reminder(self):
        queue_booking_event(self.booking, "confirmation")
        queue_due_reminders()
        with patch("django.utils.timezone.now", return_value=self.start + timedelta(minutes=15)):
            self.assertEqual(send_due_notifications(), 2)
        self.assertEqual(EmailToken.objects.filter(purpose=EmailToken.Purpose.CHECK_IN).count(), 0)
        self.assertNotIn("/check-in/link/", html_part(self.organizer_mail()))
        self.assertEqual(
            Notification.objects.filter(event_type="reminder", status=Notification.Status.SKIPPED).count(), 2
        )

    def test_stale_revision_cannot_deliver_html_or_mint_a_checkin_link(self):
        queue_booking_event(self.booking, "confirmation")
        self.booking.revision += 1
        self.booking.save(update_fields=["revision"])
        self.assertEqual(send_due_notifications(), 0)
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailToken.objects.filter(purpose=EmailToken.Purpose.CHECK_IN).count(), 0)
        self.assertEqual(Notification.objects.filter(status=Notification.Status.SKIPPED).count(), 2)

    def test_all_booking_events_have_branded_html_without_checkin_for_terminal_states(self):
        states = {
            "request": Reservation.Status.PENDING,
            "change": Reservation.Status.APPROVED,
            "rejection": Reservation.Status.REJECTED,
            "cancellation": Reservation.Status.CANCELLED,
            "no_show": Reservation.Status.NO_SHOW,
            "check_in": Reservation.Status.CHECKED_IN,
        }
        for event, status in states.items():
            with self.subTest(event=event):
                mail.outbox.clear()
                Notification.objects.all().delete()
                self.booking.status = status
                self.booking.rejection_reason = "No availability <unsafe>"
                self.booking.rejected_at = NOW
                self.booking.cancellation_reason = "Cancelled <unsafe>"
                self.booking.save()
                queue_booking_event(self.booking, event)
                self.assertGreater(send_due_notifications(), 0)
                html = html_part(self.organizer_mail())
                self.assertIn("cid:" + EMAIL_LOGO_CID, html)
                self.assertIn("View meeting", html)
                if event != "change":
                    self.assertNotIn("/check-in/link/", html)
                if event in {"rejection", "cancellation"}:
                    self.assertIn("&lt;unsafe&gt;", html)
                if event == "no_show":
                    self.assertIn("marked No show", html)
                    self.assertIn("marked No show", self.organizer_mail().body)
                    self.assertNotIn("automatically cancelled", html)

    def test_conflict_notice_has_html_booking_action_and_plain_fallback(self):
        queue_conflict_notice(self.organizer.email, "Room <A>", "2026-10-08", "09:30")
        self.assertEqual(send_due_notifications(), 1)
        message = self.organizer_mail()
        html = html_part(message)
        self.assertIn("Room <A>", message.body)
        self.assertIn("Room &lt;A&gt;", html)
        self.assertIn(f'href="{PUBLIC_ORIGIN + reverse("booking-new")}"', html)
        self.assertNotIn("/check-in/link/", html)

    def test_failed_html_delivery_preserves_retry_and_does_not_log_content(self):
        queue_booking_event(self.booking, "confirmation")
        secret = "sensitive token that must not be logged"
        with self.assertLogs("booking.services", level="WARNING") as captured:
            with patch(
                "booking.services.mail_delivery.EmailMultiAlternatives.send", side_effect=OSError(secret)
            ):
                self.assertEqual(send_due_notifications(limit=1), 0)
        failed = Notification.objects.get(status=Notification.Status.FAILED)
        self.assertEqual(failed.last_error, "OSError")
        self.assertIsNone(failed.sent_at)
        self.assertIsNone(failed.lease_token)
        self.assertEqual(failed.attempts, 1)
        self.assertGreater(failed.next_attempt_at, NOW)
        self.assertNotIn(secret, "\n".join(captured.output))
        self.assertNotIn(self.booking.title, "\n".join(captured.output))
