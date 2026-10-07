import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

from django.conf import settings
from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from booking.models import EmailToken, Room, User


class ProductionTransportConfigurationTests(SimpleTestCase):
    """Import settings in clean processes so each transport is independently checked."""

    def configuration(self, **changes):
        env = {
            "DJANGO_SECRET_KEY": "s" * 70,
            "DJANGO_ALLOWED_HOSTS": "mbs.wdn.com.np",
            "DJANGO_PUBLIC_BASE_URL": "http://mbs.wdn.com.np:8080",
            "DJANGO_PRODUCTION": "true",
            "DJANGO_HTTPS": "false",
            "DJANGO_EMAIL_BACKEND": "disabled",
            "POSTGRES_DB": "test",
            "POSTGRES_USER": "test",
            "POSTGRES_PASSWORD": "test",
            "POSTGRES_HOST": "db",
        }
        if "SystemRoot" in os.environ:
            env["SystemRoot"] = os.environ["SystemRoot"]
        env.update(changes)
        keys = (
            "PRODUCTION_ENABLED",
            "HTTPS_ENABLED",
            "SECURE_SSL_REDIRECT",
            "SECURE_REFERRER_POLICY",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "SESSION_COOKIE_HTTPONLY",
            "SESSION_COOKIE_SAMESITE",
            "CSRF_USE_SESSIONS",
            "SECURE_HSTS_SECONDS",
            "SECURE_PROXY_SSL_HEADER",
            "CSRF_TRUSTED_ORIGINS",
            "EMAIL_BACKEND",
            "DEBUG",
        )
        program = (
            "import json, runpy, sys; "
            "configured=runpy.run_path(sys.argv[1]); "
            f"print(json.dumps({{key: configured[key] for key in {keys!r}}}))"
        )
        result = subprocess.run(
            [sys.executable, "-c", program, str(Path(settings.BASE_DIR) / "config" / "settings.py")],
            env=env,
            capture_output=True,
            text=True,
            timeout=10,
        )
        return result

    def loaded(self, **changes):
        result = self.configuration(**changes)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def test_http_production_keeps_authentication_protections_without_https_redirect(self):
        configured = self.loaded()
        self.assertTrue(configured["PRODUCTION_ENABLED"])
        for field in (
            "HTTPS_ENABLED",
            "SECURE_SSL_REDIRECT",
            "SESSION_COOKIE_SECURE",
            "CSRF_COOKIE_SECURE",
            "DEBUG",
        ):
            self.assertFalse(configured[field], field)
        self.assertTrue(configured["SESSION_COOKIE_HTTPONLY"])
        self.assertEqual(configured["SESSION_COOKIE_SAMESITE"], "Lax")
        self.assertTrue(configured["CSRF_USE_SESSIONS"])
        self.assertEqual(configured["SECURE_HSTS_SECONDS"], 0)
        self.assertIsNone(configured["SECURE_PROXY_SSL_HEADER"])
        self.assertEqual(configured["CSRF_TRUSTED_ORIGINS"], ["http://mbs.wdn.com.np:8080"])
        self.assertEqual(configured["SECURE_REFERRER_POLICY"], "same-origin")

    def test_https_retains_production_protections_for_existing_deployments(self):
        configured = self.loaded(
            DJANGO_PRODUCTION="false",
            DJANGO_HTTPS="true",
            DJANGO_PUBLIC_BASE_URL="https://mbs.wdn.com.np",
        )
        self.assertTrue(configured["PRODUCTION_ENABLED"])
        self.assertTrue(configured["SECURE_SSL_REDIRECT"])
        self.assertTrue(configured["SESSION_COOKIE_SECURE"])
        self.assertEqual(configured["CSRF_TRUSTED_ORIGINS"], ["https://mbs.wdn.com.np"])

    def test_development_file_email_still_works(self):
        configured = self.loaded(DJANGO_PRODUCTION="false", DJANGO_EMAIL_BACKEND="file")
        self.assertFalse(configured["PRODUCTION_ENABLED"])
        self.assertEqual(configured["EMAIL_BACKEND"], "django.core.mail.backends.filebased.EmailBackend")
        self.assertEqual(configured["CSRF_TRUSTED_ORIGINS"], [])

    def test_production_file_email_is_rejected_over_http_and_https(self):
        for changes in ({}, {"DJANGO_HTTPS": "true", "DJANGO_PUBLIC_BASE_URL": "https://mbs.wdn.com.np"}):
            with self.subTest(changes=changes):
                result = self.configuration(DJANGO_EMAIL_BACKEND="file", **changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("local HTTP development only", result.stderr)

    def test_production_requires_explicit_hosts_and_long_secret(self):
        for changes in (
            {"DJANGO_SECRET_KEY": "too-short"},
            {"DJANGO_ALLOWED_HOSTS": "mbs.wdn.com.np,*"},
            {"DJANGO_ALLOWED_HOSTS": "mbs.wdn.com.np,.wdn.com.np"},
        ):
            with self.subTest(changes=changes):
                result = self.configuration(**changes)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("explicit allowed hosts", result.stderr)

    def test_public_origin_must_match_production_transport_and_allowed_hostname(self):
        for changes in (
            {"DJANGO_PUBLIC_BASE_URL": "https://mbs.wdn.com.np"},
            {"DJANGO_HTTPS": "true"},
            {"DJANGO_PUBLIC_BASE_URL": "http://unrelated.invalid"},
            {"DJANGO_PUBLIC_BASE_URL": "http://mbs.wdn.com.np/path"},
        ):
            with self.subTest(changes=changes):
                self.assertNotEqual(self.configuration(**changes).returncode, 0)

    def test_http_smtp_configuration_is_supported(self):
        configured = self.loaded(
            DJANGO_EMAIL_BACKEND="smtp",
            SMTP_HOST="relay.invalid",
            DJANGO_FROM_EMAIL="mbs@wdn.com.np",
            SMTP_PORT="25",
            SMTP_USE_TLS="false",
            SMTP_USE_SSL="false",
        )
        self.assertEqual(configured["EMAIL_BACKEND"], "django.core.mail.backends.smtp.EmailBackend")

    def test_invalid_production_flag_is_rejected(self):
        result = self.configuration(DJANGO_PRODUCTION="treu")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("DJANGO_PRODUCTION must be true or false", result.stderr)


@override_settings(
    ALLOWED_HOSTS=["mbs.wdn.com.np", "localhost"],
    PRODUCTION_ENABLED=True,
    HTTPS_ENABLED=False,
    PUBLIC_BASE_URL="http://mbs.wdn.com.np:8080",
    SECURE_SSL_REDIRECT=False,
    SECURE_PROXY_SSL_HEADER=None,
    SESSION_COOKIE_SECURE=False,
    CSRF_COOKIE_SECURE=False,
    SECURE_HSTS_SECONDS=0,
    CSRF_TRUSTED_ORIGINS=["http://mbs.wdn.com.np:8080"],
    MAIL_MODE="smtp",
    EMAIL_READY=True,
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class ProductionHttpAuthenticationTests(TestCase):
    host = "mbs.wdn.com.np"
    origin = "http://mbs.wdn.com.np:8080"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def page_token(self, name, **headers):
        response = self.client.get(reverse(name), HTTP_HOST=self.host, **headers)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)

    def post(self, name, data, token=None, origin=None):
        if token is not None:
            data = {**data, "csrfmiddlewaretoken": token}
        return self.client.post(reverse(name), data, HTTP_HOST=self.host, HTTP_ORIGIN=origin or self.origin)

    def test_employee_and_staff_forms_preserve_same_origin_browser_post_headers(self):
        for route in ("sign-in", "staff-login"):
            with self.subTest(route=route):
                response = self.client.get(reverse(route), HTTP_HOST=self.host)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response["Referrer-Policy"], "same-origin")
                self.assertContains(response, 'name="csrfmiddlewaretoken"')

    def test_public_http_port_passes_csrf_and_cookie_remains_httponly(self):
        token = self.page_token("staff-login")
        response = self.post("staff-login", {}, token)
        self.assertEqual(response.status_code, 200)
        cookie = self.client.cookies[settings.SESSION_COOKIE_NAME]
        self.assertFalse(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")
        self.assertNotIn("Strict-Transport-Security", response)
        self.assertIn("Content-Security-Policy", response)

    def test_wrong_origins_fail_even_with_valid_token(self):
        token = self.page_token("staff-login")
        for origin in ("http://unrelated.invalid", "http://mbs.wdn.com.np:8081", "null"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post("staff-login", {}, token, origin).status_code, 403)

    def test_correct_origin_requires_session_csrf_token(self):
        self.page_token("staff-login")
        self.assertEqual(self.post("staff-login", {}).status_code, 403)

    def test_production_does_not_allow_loopback_opaque_origin(self):
        page = self.client.get(reverse("staff-login"), HTTP_HOST="localhost")
        token = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', page.content.decode()).group(1)
        response = self.client.post(
            reverse("staff-login"),
            {"csrfmiddlewaretoken": token},
            HTTP_HOST="localhost",
            HTTP_ORIGIN="null",
        )
        self.assertEqual(response.status_code, 403)

    @override_settings(MAIL_MODE="file")
    def test_production_dev_inbox_is_hidden_even_if_mail_settings_are_overridden(self):
        self.assertEqual(self.client.get(reverse("dev-mail"), HTTP_HOST="localhost").status_code, 404)
        employee_page = self.client.get(reverse("sign-in"), HTTP_HOST="localhost")
        session = self.client.session
        session["pending_staff_token_id"] = 999
        session.save()
        staff_page = self.client.get(reverse("staff-code"), HTTP_HOST="localhost")
        self.assertFalse(employee_page.context["local_mail"])
        self.assertFalse(staff_page.context["local_mail"])

    @override_settings(MAIL_MODE="file")
    def test_production_demo_seed_is_denied_before_creating_data(self):
        with self.assertRaisesMessage(CommandError, "restricted to local"):
            call_command("seed_demo_rooms", verbosity=0)
        self.assertFalse(Room.objects.exists())

    def test_employee_http_link_still_requires_confirmation_and_is_single_use(self):
        token = self.page_token("sign-in")
        response = self.post("sign-in", {"email": "employee@wdn.com.np"}, token)
        self.assertEqual(response.status_code, 200)
        link = re.search(r"http://\S+/sign-in/link/\S+", mail.outbox[0].body).group()
        self.assertTrue(link.startswith(self.origin + "/"))
        self.client.get(urlsplit(link).path, HTTP_HOST=self.host)
        self.assertNotIn("_auth_user_id", self.client.session)
        confirmation = self.page_token("login-confirm")
        self.assertEqual(self.post("login-confirm", {}, confirmation).status_code, 302)
        self.assertIn("_auth_user_id", self.client.session)
        issued = EmailToken.objects.get()
        self.assertIsNotNone(issued.consumed_at)
        self.client.logout()
        self.client.get(urlsplit(link).path, HTTP_HOST=self.host)
        confirmation = self.page_token("login-confirm")
        self.assertEqual(self.post("login-confirm", {}, confirmation).status_code, 400)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_staff_http_sign_in_still_requires_password_and_email_code(self):
        password = "PrivateOfficeStaff2026!"
        User.objects.create_user("desk@wdn.com.np", password, is_staff=True)
        token = self.page_token("staff-login")
        self.assertEqual(
            self.post("staff-login", {"email": "desk@wdn.com.np", "password": "wrong"}, token).status_code,
            200,
        )
        self.assertFalse(EmailToken.objects.exists())
        self.assertEqual(
            self.post("staff-login", {"email": "desk@wdn.com.np", "password": password}, token).status_code,
            302,
        )
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertEqual(self.client.get(reverse("staff-dashboard"), HTTP_HOST=self.host).status_code, 302)
        code = re.search(r"\b\d{8}\b", mail.outbox[0].body).group()
        csrf = self.page_token("staff-code")
        self.assertEqual(self.post("staff-code", {"code": code}, csrf).status_code, 302)
        self.assertTrue(self.client.session["staff_verified"])
        self.assertEqual(self.client.get(reverse("staff-dashboard"), HTTP_HOST=self.host).status_code, 200)
