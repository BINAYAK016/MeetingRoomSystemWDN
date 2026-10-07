import re

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.sessions.models import Session
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import reverse

from booking.views import csrf_failure


@override_settings(
    ALLOWED_HOSTS=["mbs.wdn.com.np"],
    PRODUCTION_ENABLED=True,
    HTTPS_ENABLED=False,
    SECURE_SSL_REDIRECT=False,
    SESSION_COOKIE_SECURE=False,
    CSRF_TRUSTED_ORIGINS=["http://mbs.wdn.com.np"],
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
)
class CsrfRejectionDiagnosticsTests(TestCase):
    host = "mbs.wdn.com.np"
    origin = "http://mbs.wdn.com.np"

    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)

    def form_token(self):
        response = self.client.get(reverse("sign-in"), HTTP_HOST=self.host)
        self.assertEqual(response.status_code, 200)
        return re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()).group(1)

    def rejected(self, category, *, route="sign-in", data=None, **headers):
        with self.assertLogs("booking.views", level="WARNING") as captured:
            response = self.client.post(
                reverse(route),
                data or {},
                HTTP_HOST=self.host,
                HTTP_ORIGIN=headers.pop("HTTP_ORIGIN", self.origin),
                **headers,
            )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(len(captured.records), 1)
        self.assertEqual(
            captured.records[0].getMessage(),
            f"CSRF request rejected category={category} request_id={response['X-Request-ID']}",
        )
        self.assertIn("no-store", response["Cache-Control"])
        return response, captured.output

    def test_absent_or_deleted_session_is_identified_without_cookie_values(self):
        token = self.form_token()
        session_cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value
        self.client.cookies.clear()
        response, logs = self.rejected("missing_session", data={"csrfmiddlewaretoken": token})
        self.assertContains(response, f'href="{reverse("sign-in")}"', status_code=403)
        self.assertNotIn(session_cookie, str(logs))
        self.assertNotIn(token, str(logs))

        token = self.form_token()
        Session.objects.filter(session_key=self.client.cookies[settings.SESSION_COOKIE_NAME].value).delete()
        self.rejected("missing_session", data={"csrfmiddlewaretoken": token})

    def test_missing_form_token_with_valid_session_is_identified(self):
        self.form_token()
        self.rejected("missing_token")

    def test_invalid_form_token_is_identified_without_logging_its_value(self):
        token = self.form_token()
        changed = ("a" if token[0] != "a" else "b") + token[1:]
        _, logs = self.rejected("invalid_token", data={"csrfmiddlewaretoken": changed})
        self.assertNotIn(changed, str(logs))

    def test_wrong_origin_never_logs_sensitive_origin_or_request_values(self):
        token = self.form_token()
        secret = "private-origin-and-password-value"
        response, logs = self.rejected(
            "origin_mismatch",
            data={"csrfmiddlewaretoken": token, "password": secret},
            HTTP_ORIGIN=f"https://outside.invalid/{secret}",
            HTTP_REFERER=f"https://outside.invalid/{secret}",
            HTTP_X_REQUEST_ID=secret,
        )
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9]{32}$")
        for value in (secret, token, "outside.invalid"):
            self.assertNotIn(value, str(logs))
            self.assertNotIn(value, response.content.decode())

    def test_staff_form_returns_to_staff_sign_in_and_keeps_valid_request_reference(self):
        reference = "a" * 32
        for route in ("staff-login", "staff-code"):
            with self.subTest(route=route):
                response, _ = self.rejected("missing_session", route=route, HTTP_X_REQUEST_ID=reference)
                self.assertEqual(response["X-Request-ID"], reference)
                self.assertContains(response, f'href="{reverse("staff-login")}"', status_code=403)
                self.assertContains(response, "Return to staff sign-in", status_code=403)
                self.assertNotContains(response, "same local address", status_code=403)

    def test_unknown_reason_and_invalid_reference_are_reduced_to_fixed_labels(self):
        secret = "private-reason-session-token"
        request = RequestFactory().post(reverse("sign-in"), HTTP_HOST=self.host)
        request.user = AnonymousUser()
        request.request_id = secret
        with self.assertLogs("booking.views", level="WARNING") as captured:
            response = csrf_failure(request, reason=f"Unexpected rejection {secret}")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(
            captured.records[0].getMessage(), "CSRF request rejected category=other request_id=unavailable"
        )
        self.assertNotIn(secret, str(captured.output))
        self.assertNotIn(secret, response.content.decode())

    def test_https_request_with_missing_referer_is_identified(self):
        self.form_token()
        with override_settings(
            SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"), CSRF_TRUSTED_ORIGINS=[]
        ):
            with self.assertLogs("booking.views", level="WARNING") as captured:
                response = self.client.post(
                    reverse("sign-in"), HTTP_HOST=self.host, HTTP_X_FORWARDED_PROTO="https"
                )
        self.assertEqual(response.status_code, 403)
        self.assertIn("category=referer_rejected", captured.records[0].getMessage())
