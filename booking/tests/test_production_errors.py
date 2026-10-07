import json
import logging
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

from django.conf import settings
from django.db import OperationalError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from booking.logging import SafeExceptionLogFilter, SafeGunicornLogFilter
from booking.models import User


class SafeRuntimeLoggingTests(SimpleTestCase):
    def test_exception_logs_keep_source_without_secret_values_or_request_urls(self):
        secret = "private-password-token"
        for log_filter in (SafeExceptionLogFilter(), SafeGunicornLogFilter()):
            try:
                raise RuntimeError(secret)
            except RuntimeError as exception:
                record = logging.LogRecord(
                    "booking",
                    logging.ERROR,
                    __file__,
                    1,
                    "Error handling request /sign-in/link/%s/",
                    (secret,),
                    (RuntimeError, exception, exception.__traceback__),
                )
            log_filter.filter(record)
            text = logging.Formatter("%(message)s").format(record)
            self.assertNotIn(secret, text)
            self.assertNotIn("/sign-in/link/", text)
            self.assertIn("exception=RuntimeError", text)
            self.assertIn("test_exception_logs_keep_source", text)
            self.assertIsNone(record.exc_info)

    def test_gunicorn_request_error_without_trace_never_logs_signed_path(self):
        record = logging.LogRecord(
            "gunicorn.error",
            logging.ERROR,
            __file__,
            1,
            "Error handling request %s",
            ("/check-in/link/private-token/",),
            None,
        )
        SafeGunicornLogFilter().filter(record)
        self.assertNotIn("private-token", record.getMessage())


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class SessionOutageTests(TestCase):
    def setUp(self):
        self.client = Client(raise_request_exception=False)
        self.employee = User.objects.create_user("recovery@transgate.com.np")
        self.client.force_login(self.employee)
        self.cookie = self.client.cookies[settings.SESSION_COOKIE_NAME].value

    def assert_safe_outage(self, response, secret):
        self.assertEqual(response.status_code, 503)
        self.assertContains(response, "temporarily unavailable", status_code=503)
        self.assertNotIn(secret, response.content.decode())
        self.assertEqual(response["Retry-After"], "30")
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9]{32}$")
        self.assertContains(response, response["X-Request-ID"], status_code=503)
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])
        self.assertEqual(self.client.cookies[settings.SESSION_COOKIE_NAME].value, self.cookie)

    def test_session_read_failure_returns_503_and_recovers_without_logout(self):
        secret = "private-db-connection-string"
        with patch(
            "django.contrib.sessions.backends.db.SessionStore.load", side_effect=OperationalError(secret)
        ):
            response = self.client.get(reverse("staff-login"))
        self.assert_safe_outage(response, secret)
        self.assertEqual(self.client.get(reverse("rooms")).status_code, 200)

    def test_session_save_failure_returns_503_instead_of_a_recoverable_500(self):
        secret = "private-db-password"
        with patch(
            "django.contrib.sessions.backends.db.SessionStore.save", side_effect=OperationalError(secret)
        ):
            response = self.client.get(reverse("staff-login"))
        self.assert_safe_outage(response, secret)
        self.assertEqual(self.client.get(reverse("rooms")).status_code, 200)

    def test_request_reference_and_security_headers_exist_on_csrf_failure(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse("staff-login"), {}, HTTP_X_REQUEST_ID="invalid-header-value")
        self.assertEqual(response.status_code, 403)
        self.assertRegex(response["X-Request-ID"], r"^[a-f0-9]{32}$")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn("frame-ancestors 'none'", response["Content-Security-Policy"])

    def test_unexpected_error_is_500_without_exposing_internal_details(self):
        secret = "private-internal-value"
        with patch("booking.booking_views.Room.objects.filter", side_effect=RuntimeError(secret)):
            response = self.client.get(reverse("rooms"))
        self.assertEqual(response.status_code, 500)
        self.assertContains(response, "Something went wrong", status_code=500)
        self.assertNotIn(secret, response.content.decode())
        self.assertContains(response, response["X-Request-ID"], status_code=500)
        self.assertEqual(self.client.get(reverse("rooms")).status_code, 200)


@override_settings(
    ALLOWED_HOSTS=["localhost"],
    HTTPS_ENABLED=True,
    PUBLIC_BASE_URL="https://localhost:9444",
    SECURE_SSL_REDIRECT=True,
    SECURE_PROXY_SSL_HEADER=("HTTP_X_FORWARDED_PROTO", "https"),
    SESSION_COOKIE_SECURE=True,
    CSRF_COOKIE_SECURE=True,
    CSRF_TRUSTED_ORIGINS=["https://localhost:9444"],
)
class HttpsProxyCsrfTests(TestCase):
    def setUp(self):
        self.client = Client(enforce_csrf_checks=True)
        # Nginx sends Host without the public HTTPS port to its HTTP upstream.
        response = self.client.get(
            reverse("staff-login"), HTTP_HOST="localhost", HTTP_X_FORWARDED_PROTO="https"
        )
        self.assertEqual(response.status_code, 200)
        self.token = re.search(
            r'name="csrfmiddlewaretoken" value="([^"]+)"', response.content.decode()
        ).group(1)
        cookie = response.cookies[settings.SESSION_COOKIE_NAME]
        self.assertTrue(cookie["secure"])
        self.assertTrue(cookie["httponly"])
        self.assertEqual(cookie["samesite"], "Lax")

    def post(self, **headers):
        return self.client.post(
            reverse("staff-login"),
            {"csrfmiddlewaretoken": self.token},
            HTTP_HOST="localhost",
            HTTP_X_FORWARDED_PROTO="https",
            **headers,
        )

    def test_configured_https_origin_with_port_passes_csrf(self):
        self.assertEqual(self.post(HTTP_ORIGIN="https://localhost:9444").status_code, 200)

    def test_configured_https_referer_with_port_passes_csrf(self):
        self.assertEqual(self.post(HTTP_REFERER="https://localhost:9444/staff/sign-in/").status_code, 200)

    def test_other_or_opaque_origins_are_rejected_even_with_valid_token(self):
        for origin in ("https://unrelated.invalid", "https://localhost:9445", "null"):
            with self.subTest(origin=origin):
                self.assertEqual(self.post(HTTP_ORIGIN=origin).status_code, 403)

    def test_trusted_origin_does_not_bypass_csrf_token_verification(self):
        response = self.client.post(
            reverse("staff-login"),
            {},
            HTTP_HOST="localhost",
            HTTP_X_FORWARDED_PROTO="https",
            HTTP_ORIGIN="https://localhost:9444",
        )
        self.assertEqual(response.status_code, 403)


class DeploymentHttpTests(SimpleTestCase):
    def test_idle_browser_connections_do_not_timeout_workers_or_emit_500(self):
        """Exercise the deployed Gunicorn worker configuration, without Django/DB."""
        dockerfile = (Path(settings.BASE_DIR) / "Dockerfile").read_text()
        command = json.loads(next(line[4:] for line in dockerfile.splitlines() if line.startswith("CMD ")))
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = probe.getsockname()[1]
        with tempfile.TemporaryDirectory(prefix="mbs-http-test-") as folder:
            Path(folder, "http_fixture.py").write_text(
                "def application(environ,start_response):\n"
                "    start_response('200 OK',[('Content-Type','text/plain')])\n"
                "    return [b'ok']\n"
            )
            command[0:2] = [sys.executable, "-m", "gunicorn", "http_fixture:application"]
            command[command.index("--bind") + 1] = f"127.0.0.1:{port}"
            command[command.index("--timeout") + 1] = "2"
            command.extend(["--chdir", folder])
            # The deployed logger module remains importable after changing cwd.
            command.extend(["--pythonpath", str(settings.BASE_DIR)])
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            idle = []
            output = ""
            try:
                deadline = time.monotonic() + 8
                while True:
                    try:
                        connection = socket.create_connection(("127.0.0.1", port), timeout=0.3)
                        connection.close()
                        break
                    except OSError:
                        if time.monotonic() >= deadline or process.poll() is not None:
                            self.fail("Deployment HTTP test server did not start")
                        time.sleep(0.1)
                idle = [socket.create_connection(("127.0.0.1", port), timeout=1) for _ in range(2)]
                time.sleep(3)
                for connection in idle:
                    connection.settimeout(0.15)
                    try:
                        response = connection.recv(4096)
                    except socket.timeout:
                        response = b""
                    self.assertNotIn(b"500 Internal Server Error", response)
                for path in ("/staff/sign-in/", "/rooms/"):
                    with socket.create_connection(("127.0.0.1", port), timeout=2) as connection:
                        connection.sendall(
                            f"GET {path} HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n".encode()
                        )
                        self.assertIn(b"200 OK", connection.recv(4096).split(b"\r\n", 1)[0])
            finally:
                for connection in idle:
                    connection.close()
                process.terminate()
                try:
                    output = process.communicate(timeout=5)[0]
                except subprocess.TimeoutExpired:
                    process.kill()
                    output = process.communicate()[0]
            self.assertNotIn("WORKER TIMEOUT", output)
