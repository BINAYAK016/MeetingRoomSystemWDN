import re
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
