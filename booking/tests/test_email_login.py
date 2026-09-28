import re
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import timedelta
from unittest.mock import patch

from django.core import mail
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from booking.models import AuditEvent, EmailToken, User


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class EmployeeEmailLoginTests(TestCase):
    def request_link(self, email="employee@wdn.com.np"):
        return self.client.post(reverse("sign-in"), {"email": email})

    def emailed_link(self):
        return re.search(r"https?://\S+/sign-in/link/\S+", mail.outbox[-1].body).group()

    def test_wdn_employee_can_use_one_time_link(self):
        response = self.request_link("EMPLOYEE@WDN.COM.NP")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, ["employee@wdn.com.np"])
        self.assertEqual(User.objects.count(), 0)
        self.assertNotIn("employee@wdn.com.np", response.content.decode())

        link = self.emailed_link()
        token = EmailToken.objects.get()
        self.assertNotIn(token.token_hash, link)
        confirmation = self.client.get(link)
        self.assertRedirects(confirmation, reverse("login-confirm"))
        self.assertFalse(EmailToken.objects.get().consumed_at)
        self.assertFalse(User.objects.exists())
        self.assertEqual(self.client.get(reverse("login-confirm")).status_code, 200)
        self.assertEqual(self.client.post(reverse("login-confirm")).status_code, 302)
        self.assertTrue(User.objects.get().has_usable_password() is False)
        self.assertEqual(self.client.session["_auth_user_id"], str(User.objects.get().pk))
        self.assertFalse(self.client.session["staff_verified"])
        self.assertEqual(AuditEvent.objects.filter(action="employee_login", outcome="success").count(), 1)

        self.client.post(reverse("sign-out"))
        self.client.get(link)
        self.assertEqual(self.client.post(reverse("login-confirm")).status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_only_wdn_domain_is_allowed_with_generic_response(self):
        for email in ("person@example.com", "person@tgt.com.np", "bad@@wdn.com.np"):
            response = self.request_link(email)
            self.assertEqual(response.status_code, 200)
            self.assertContains(response, "If this is an eligible WDN address")
        self.assertEqual(len(mail.outbox), 0)
        self.assertEqual(EmailToken.objects.count(), 0)

    def test_expired_link_does_not_create_account(self):
        self.request_link()
        link = self.emailed_link()
        EmailToken.objects.update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.get(link)
        self.assertEqual(self.client.post(reverse("login-confirm")).status_code, 400)
        self.assertFalse(User.objects.exists())

    def test_inactive_account_receives_no_link(self):
        User.objects.create_user("employee@wdn.com.np", is_active=False)
        self.request_link()
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailToken.objects.exists())

    def test_login_link_is_rate_limited_per_address(self):
        for _ in range(4):
            self.request_link()
        self.assertEqual(len(mail.outbox), 3)
        self.assertEqual(EmailToken.objects.count(), 3)

    def test_email_delivery_failure_invalidates_link(self):
        with patch("booking.services.email_login.send_mail", side_effect=OSError("relay unavailable")):
            self.request_link()
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNotNone(EmailToken.objects.get().consumed_at)

    def test_confirm_requires_csrf_token(self):
        self.request_link()
        link = self.emailed_link()
        protected = Client(enforce_csrf_checks=True)
        protected.get(link)
        self.assertEqual(protected.post(reverse("login-confirm")).status_code, 403)
        self.assertIsNone(EmailToken.objects.get().consumed_at)

    def test_sign_in_uses_session_csrf_protection(self):
        protected = Client(enforce_csrf_checks=True)
        page = protected.get(reverse("sign-in"))
        self.assertEqual(page.status_code, 200)
        self.assertIn("sessionid", protected.cookies)
        self.assertNotIn("csrftoken", protected.cookies)
        rejected = protected.post(reverse("sign-in"), {"email": "employee@wdn.com.np"})
        self.assertEqual(rejected.status_code, 403)
        self.assertContains(rejected, "Let’s start fresh", status_code=403)
        self.assertFalse(EmailToken.objects.exists())

    def test_local_opaque_browser_origin_requires_valid_session_token(self):
        protected = Client(enforce_csrf_checks=True)
        page = protected.get(reverse("sign-in"), HTTP_HOST="127.0.0.1:8000")
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        rejected = protected.post(
            reverse("sign-in"),
            {"email": "employee@wdn.com.np"},
            HTTP_HOST="127.0.0.1:8000",
            HTTP_ORIGIN="null",
        )
        self.assertEqual(rejected.status_code, 403)
        accepted = protected.post(
            reverse("sign-in"),
            {"email": "employee@wdn.com.np", "csrfmiddlewaretoken": token},
            HTTP_HOST="127.0.0.1:8000",
            HTTP_ORIGIN="null",
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(len(mail.outbox), 1)

        with override_settings(HTTPS_ENABLED=True):
            blocked = protected.post(
                reverse("sign-in"),
                {"email": "employee@wdn.com.np", "csrfmiddlewaretoken": token},
                HTTP_HOST="127.0.0.1:8000",
                HTTP_ORIGIN="null",
            )
            self.assertEqual(blocked.status_code, 403)

    def test_local_mailbox_is_only_available_in_local_mail_mode(self):
        with TemporaryDirectory() as directory:
            Path(directory, "sample.log").write_text(
                "To: employee@wdn.com.np\n\nhttp://localhost:8000/sign-in/link/sample-token\n",
                encoding="utf-8",
            )
            with override_settings(MAIL_MODE="file", EMAIL_FILE_PATH=directory, HTTPS_ENABLED=False):
                response = self.client.get(reverse("dev-mail"), HTTP_HOST="localhost")
                self.assertContains(response, "employee@wdn.com.np")
                self.assertContains(response, "sample-token")
                self.assertNotIn("flash-stack", response.content.decode())
            with override_settings(MAIL_MODE="smtp", HTTPS_ENABLED=True):
                self.assertEqual(self.client.get(reverse("dev-mail"), HTTP_HOST="localhost").status_code, 404)
