import hashlib
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier, Event
from unittest.mock import patch

from django.contrib.auth.models import AnonymousUser
from django.contrib.auth.tokens import default_token_generator
from django.contrib.sessions.backends.db import SessionStore
from django.contrib.sessions.models import Session
from django.core import mail
from django.db import OperationalError, connection, connections, transaction
from django.test import Client, RequestFactory, TestCase, TransactionTestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlsafe_base64_encode

from booking.logging import SafeRequestLogFilter
from booking.models import AuditEvent, AuthenticationThrottle, EmailToken, Room, User
from booking.services.auth_security import allow_auth_request, client_ip
from booking.services.email_login import consume_login_link, get_or_create_employee, request_login_link
from booking.services.staff_auth import finish_staff_login

PASSWORD = "OfficeDeskPassphrase2026!"


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthenticationSecurityTests(TestCase):
    def setUp(self):
        self.employee = User.objects.create_user("employee@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", PASSWORD, is_staff=True)
        self.room = Room.objects.create(name="Office room", location="WDN", floor="2", capacity=8)

    def issue_code(self):
        response = self.client.post(reverse("staff-login"), {"email": self.staff.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        token = EmailToken.objects.filter(purpose="staff").latest("pk")
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group()
        return token, code

    def staff_sign_in(self):
        token, code = self.issue_code()
        self.assertRedirects(
            self.client.post(reverse("staff-code"), {"code": code}), reverse("staff-dashboard")
        )
        return token

    def password_url(self):
        self.staff.refresh_from_db()
        uid = urlsafe_base64_encode(str(self.staff.pk).encode())
        return reverse("staff-set-password", args=[uid, default_token_generator.make_token(self.staff)])

    def test_wrong_password_is_generic_and_does_not_issue_token(self):
        response = self.client.post(
            reverse("staff-login"), {"email": self.staff.email, "password": "WrongPassword!"}
        )
        self.assertContains(response, "Sign-in could not be completed")
        self.assertFalse(EmailToken.objects.exists())
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertTrue(AuditEvent.objects.filter(action="staff_password_failed", outcome="denied").exists())

    def test_staff_password_limit_spans_client_addresses(self):
        for number in range(5):
            self.client.post(
                reverse("staff-login"),
                {"email": self.staff.email, "password": "wrong"},
                REMOTE_ADDR=f"10.0.0.{number + 1}",
            )
        response = self.client.post(
            reverse("staff-login"), {"email": self.staff.email, "password": PASSWORD}, REMOTE_ADDR="10.0.0.20"
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(EmailToken.objects.exists())
        counter = AuthenticationThrottle.objects.get(purpose="staff_password_account")
        self.assertEqual(counter.attempts, 5)
        self.assertNotIn(self.staff.email, counter.key)

    def test_otp_attempts_cannot_be_reset_in_session_and_code_is_single_use(self):
        token, correct = self.issue_code()
        wrong = "00000000" if correct != "00000000" else "11111111"
        for _ in range(5):
            session = self.client.session
            session["staff_code_attempts"] = 0
            session.save()
            self.client.post(reverse("staff-code"), {"code": wrong})
        token.refresh_from_db()
        self.assertEqual(token.attempts, 5)
        self.assertIsNotNone(token.consumed_at)
        session = self.client.session
        session["pending_staff_token_id"] = token.pk
        session.save()
        self.client.post(reverse("staff-code"), {"code": correct})
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_expired_and_replayed_codes_do_not_authenticate(self):
        token, code = self.issue_code()
        EmailToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
        self.client.post(reverse("staff-code"), {"code": code})
        self.assertNotIn("_auth_user_id", self.client.session)
        token = self.staff_sign_in()
        self.client.post(reverse("sign-out"))
        session = self.client.session
        session["pending_staff_token_id"] = token.pk
        session.save()
        self.client.post(
            reverse("staff-code"), {"code": re.search(r"\b\d{8}\b", mail.outbox[-1].body).group()}
        )
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_reissued_code_has_unique_hash_and_invalidates_previous_challenge(self):
        with patch("booking.services.staff_auth.secrets.randbelow", return_value=12345678):
            first, code = self.issue_code()
            second, repeated = self.issue_code()
        first.refresh_from_db()
        self.assertIsNotNone(first.consumed_at)
        self.assertEqual(code, repeated)
        self.assertNotEqual(first.token_hash, second.token_hash)
        self.assertEqual(self.client.post(reverse("staff-code"), {"code": repeated}).status_code, 302)

    def test_staff_mail_failure_does_not_start_authentication(self):
        with patch(
            "booking.services.staff_auth.deliver_mail", side_effect=RuntimeError("delivery unavailable")
        ):
            response = self.client.post(
                reverse("staff-login"), {"email": self.staff.email, "password": PASSWORD}
            )
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("pending_staff_token_id", self.client.session)
        self.assertIsNotNone(EmailToken.objects.get().consumed_at)
        self.assertTrue(
            AuditEvent.objects.filter(action="staff_login_email_failed", outcome="failed").exists()
        )

    @override_settings(
        EMAIL_BACKEND="booking.mail_backends.DisabledEmailBackend", MAIL_MODE="disabled", EMAIL_READY=False
    )
    def test_disabled_email_is_clear_and_never_claims_a_link_was_sent(self):
        response = self.client.post(reverse("sign-in"), {"email": self.employee.email})
        self.assertContains(response, "Sign-in email is unavailable.")
        self.assertNotContains(response, "we’ve sent")
        self.assertNotContains(response, "a sign-in link will arrive")
        self.assertNotContains(response, "Open local test inbox")
        self.assertEqual(len(mail.outbox), 0)
        self.assertIsNotNone(EmailToken.objects.get(purpose="login").consumed_at)

    def test_generic_sign_in_response_does_not_claim_successful_delivery(self):
        response = self.client.post(reverse("sign-in"), {"email": "person@example.com"})
        self.assertContains(response, "If the address is eligible and delivery is available")
        self.assertNotContains(response, "we’ve sent")
        self.assertEqual(len(mail.outbox), 0)

    def test_authentication_failure_logs_exclude_passwords_and_mail_secrets(self):
        secret = "smtp-secret-that-must-not-appear"
        with self.assertLogs("booking", level="WARNING") as captured:
            with patch("booking.services.staff_auth.deliver_mail", side_effect=RuntimeError(secret)):
                self.client.post(reverse("staff-login"), {"email": self.staff.email, "password": PASSWORD})
        self.assertNotIn(secret, "\n".join(captured.output))
        self.assertNotIn(PASSWORD, "\n".join(captured.output))

    def test_request_error_filter_removes_signed_urls_payloads_and_exception_values(self):
        secret = "never-log-this-token-or-password"
        request = RequestFactory().post(
            f"/sign-in/link/{secret}/", {"password": secret}, HTTP_AUTHORIZATION=secret
        )
        try:
            raise ValueError(secret)
        except ValueError as exc:
            record = logging.LogRecord(
                "django.request",
                logging.ERROR,
                __file__,
                1,
                "Internal Server Error: %s",
                (request.path,),
                (ValueError, exc, exc.__traceback__),
            )
        record.request = request
        record.status_code = 500
        SafeRequestLogFilter().filter(record)
        output = logging.Formatter("%(message)s").format(record)
        self.assertNotIn(secret, output)
        self.assertIn("method=POST", output)
        self.assertIn("status=500", output)
        self.assertIn("exception=ValueError", output)
        self.assertIn("test_request_error_filter", output)
        self.assertIsNone(record.exc_info)

    def test_authenticated_responses_are_not_cached_and_database_failure_is_safe(self):
        self.client.force_login(self.employee)
        response = self.client.get(reverse("rooms"))
        self.assertIn("no-store", response["Cache-Control"])
        with self.assertLogs("booking", level="ERROR") as captured:
            with patch(
                "booking.booking_views.Room.objects.filter",
                side_effect=OperationalError("private-database-password"),
            ):
                response = self.client.get(reverse("rooms"))
        self.assertContains(response, "temporarily unavailable", status_code=503)
        self.assertEqual(response["Retry-After"], "30")
        self.assertNotIn("private-database-password", response.content.decode())
        self.assertNotIn("private-database-password", "\n".join(captured.output))

    @override_settings(PUBLIC_BASE_URL="https://rooms.wdn.com.np")
    def test_employee_link_uses_configured_origin(self):
        self.client.post(reverse("sign-in"), {"email": self.employee.email}, HTTP_HOST="localhost")
        self.assertIn("https://rooms.wdn.com.np/sign-in/link/", mail.outbox[-1].body)
        self.assertNotIn("http://localhost/sign-in/link/", mail.outbox[-1].body)

    def test_logout_and_database_session_expiry_remove_access(self):
        self.staff_sign_in()
        self.assertTrue(self.client.session["staff_verified"])
        self.assertEqual(self.client.session["staff_auth_version"], self.staff.auth_version)
        self.assertEqual(self.client.session.get_expiry_age(), 8 * 60 * 60)
        self.client.post(reverse("sign-out"))
        self.assertNotIn("_auth_user_id", self.client.session)
        self.assertRedirects(self.client.get(reverse("staff-dashboard")), reverse("staff-login"))
        self.client.force_login(self.employee)
        Session.objects.filter(session_key=self.client.session.session_key).update(
            expire_date=timezone.now() - timedelta(seconds=1)
        )
        self.assertEqual(self.client.get(reverse("rooms")).status_code, 302)
        self.assertNotIn("_auth_user_id", self.client.session)

    def test_password_setup_invalidates_pending_codes_and_old_sessions(self):
        self.staff_sign_in()
        other = Client()
        response = other.post(reverse("staff-login"), {"email": self.staff.email, "password": PASSWORD})
        self.assertEqual(response.status_code, 302)
        token = EmailToken.objects.filter(purpose="staff", consumed_at__isnull=True).get()
        code = re.search(r"\b\d{8}\b", mail.outbox[-1].body).group()
        url = self.password_url()
        new_password = "ChangedOfficePassphrase2026!"
        response = Client().post(url, {"password": new_password, "confirm": new_password})
        self.assertEqual(response.status_code, 302)
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password(new_password))
        self.assertEqual(self.staff.auth_version, 2)
        token.refresh_from_db()
        self.assertIsNotNone(token.consumed_at)
        other.post(reverse("staff-code"), {"code": code})
        self.assertNotIn("_auth_user_id", other.session)
        self.assertRedirects(self.client.get(reverse("staff-dashboard")), reverse("staff-login"))
        self.assertEqual(Client().post(url, {"password": PASSWORD, "confirm": PASSWORD}).status_code, 404)

    def test_invalid_password_setup_does_not_change_password(self):
        response = self.client.post(self.password_url(), {"password": "123", "confirm": "123"})
        self.assertContains(response, "at least 12")
        self.staff.refresh_from_db()
        self.assertTrue(self.staff.check_password(PASSWORD))
        uid = urlsafe_base64_encode(str(self.staff.pk).encode())
        self.assertEqual(
            self.client.get(reverse("staff-set-password", args=[uid, "invalid"])).status_code, 404
        )

    def test_old_mfa_session_does_not_regain_access_after_role_change(self):
        self.staff_sign_in()
        User.objects.filter(pk=self.staff.pk).update(auth_version=self.staff.auth_version + 1)
        self.assertRedirects(self.client.get(reverse("staff-dashboard")), reverse("staff-login"))

    def test_employee_session_stays_revoked_after_deactivation_and_reactivation(self):
        employee_client = Client()
        employee_client.force_login(self.employee)
        self.assertEqual(employee_client.get(reverse("rooms")).status_code, 200)
        self.staff_sign_in()
        for active in (False, True):
            data = {"email": self.employee.email}
            if active:
                data["is_active"] = "on"
            response = self.client.post(reverse("staff-user-save"), data)
            self.assertEqual(response.status_code, 302)
        self.employee.refresh_from_db()
        self.assertTrue(self.employee.is_active)
        self.assertEqual(self.employee.auth_version, 3)
        response = employee_client.get(reverse("rooms"))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("sign-in")))
        self.assertNotIn("_auth_user_id", employee_client.session)

    @override_settings(SECRET_KEY="new-test-secret", SECRET_KEY_FALLBACKS=["old-test-secret"])
    def test_session_version_binding_preserves_secret_key_fallback_support(self):
        original = self.employee._get_session_auth_hash(secret="old-test-secret")
        self.assertIn(original, list(self.employee.get_session_auth_fallback_hash()))
        self.employee.auth_version += 1
        self.assertNotEqual(original, self.employee._get_session_auth_hash(secret="old-test-secret"))

    def test_all_staff_routes_deny_employee_and_unverified_staff(self):
        routes = [
            ("staff-dashboard", [], "get"),
            ("staff-rooms", [], "get"),
            ("staff-room-new", [], "get"),
            ("staff-room-new", [], "post"),
            ("staff-room-edit", [self.room.pk], "get"),
            ("staff-room-edit", [self.room.pk], "post"),
            ("staff-bookings", [], "get"),
            ("staff-checkin", [99999], "post"),
            ("staff-blocks", [], "get"),
            ("staff-block-new", [], "get"),
            ("staff-block-new", [], "post"),
            ("staff-block-cancel", [99999], "post"),
            ("staff-policy", [], "get"),
            ("staff-policy", [], "post"),
            ("staff-holidays", [], "get"),
            ("staff-holidays", [], "post"),
            ("staff-holiday-delete", [99999], "post"),
            ("staff-holiday-import", [], "get"),
            ("staff-holiday-import", [], "post"),
            ("staff-holiday-template", [], "get"),
            ("staff-users", [], "get"),
            ("staff-user-save", [], "post"),
            ("staff-user-setup", [self.staff.pk], "post"),
            ("staff-reports", [], "get"),
            ("staff-report-excel", [], "get"),
            ("staff-audit", [], "get"),
        ]
        for user in (None, self.employee, self.staff):
            client = Client()
            if user is not None:
                client.force_login(user)
            for name, args, method in routes:
                with self.subTest(user=user, route=name, method=method):
                    response = getattr(client, method)(reverse(name, args=args))
                    self.assertEqual(response.status_code, 302)
                    self.assertEqual(response.url, reverse("staff-login"))
        self.assertEqual(Room.objects.count(), 1)
        self.assertEqual(User.objects.count(), 2)

    @override_settings(AUTH_TRUSTED_PROXY_CIDRS=("172.29.16.0/28",))
    def test_forwarded_ip_is_trusted_only_from_configured_proxy_network(self):
        factory = RequestFactory()
        direct = factory.get("/", REMOTE_ADDR="10.0.0.8", HTTP_X_REAL_IP="10.0.0.9")
        self.assertEqual(client_ip(direct), "10.0.0.8")
        proxied = factory.get("/", REMOTE_ADDR="172.29.16.3", HTTP_X_REAL_IP="10.0.0.9")
        self.assertEqual(client_ip(proxied), "10.0.0.9")
        malformed = factory.get("/", REMOTE_ADDR="172.29.16.3", HTTP_X_REAL_IP="not-an-address")
        self.assertEqual(client_ip(malformed), "172.29.16.3")

    def test_throttle_window_expires_and_ip_limit_spans_addresses(self):
        request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.1")
        for number in range(2):
            self.assertTrue(
                allow_auth_request("test", f"user{number}@wdn.com.np", request, account_limit=1, ip_limit=2)
            )
        self.assertFalse(allow_auth_request("test", "third@wdn.com.np", request, account_limit=1, ip_limit=2))
        self.assertFalse(
            AuthenticationThrottle.objects.filter(purpose="test_account", key__contains="wdn").exists()
        )
        AuthenticationThrottle.objects.update(window_started_at=timezone.now() - timedelta(minutes=16))
        self.assertTrue(allow_auth_request("test", "third@wdn.com.np", request, account_limit=1, ip_limit=2))


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class AuthenticationConcurrencyTests(TransactionTestCase):
    def request(self, token_id=None):
        request = RequestFactory().post("/", REMOTE_ADDR="10.0.0.1")
        request.user = AnonymousUser()
        request.session = SessionStore()
        if token_id is not None:
            request.session["pending_staff_token_id"] = token_id
        return request

    def parallel(self, count, action):
        barrier = Barrier(count)

        def run(number):
            connections.close_all()
            try:
                barrier.wait(timeout=10)
                return action(number)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=count) as executor:
            return list(executor.map(run, range(count)))

    def staff_token(self):
        staff = User.objects.create_user("desk@wdn.com.np", PASSWORD, is_staff=True)
        client = Client()
        client.post(reverse("staff-login"), {"email": staff.email, "password": PASSWORD})
        token = EmailToken.objects.get(purpose="staff")
        return token, re.search(r"\b\d{8}\b", mail.outbox[-1].body).group()

    def test_concurrent_wrong_otp_attempts_stop_at_five(self):
        token, correct = self.staff_token()
        wrong = "00000000" if correct != "00000000" else "11111111"
        results = self.parallel(8, lambda _: finish_staff_login(wrong, self.request(token.pk)))
        self.assertFalse(any(results))
        token.refresh_from_db()
        self.assertEqual(token.attempts, 5)
        self.assertIsNotNone(token.consumed_at)

    def test_concurrent_valid_otp_is_consumed_once(self):
        token, code = self.staff_token()
        results = self.parallel(2, lambda _: finish_staff_login(code, self.request(token.pk)))
        self.assertEqual(sorted(results), [False, True])
        self.assertEqual(AuditEvent.objects.filter(action="staff_login").count(), 1)

    def test_concurrent_sender_throttle_creates_only_three_tokens(self):
        with patch("booking.services.email_login.deliver_mail", return_value=1):
            results = self.parallel(6, lambda _: request_login_link("employee@wdn.com.np", self.request()))
        self.assertEqual(results.count(True), 3)
        self.assertEqual(EmailToken.objects.filter(purpose="login").count(), 3)

    def test_separate_login_tokens_create_one_employee_under_concurrency(self):
        raw_tokens = ["first-valid-employee-token", "second-valid-employee-token"]
        for raw in raw_tokens:
            EmailToken.objects.create(
                email="new@wdn.com.np",
                purpose="login",
                token_hash=hashlib.sha256(raw.encode()).hexdigest(),
                expires_at=timezone.now() + timedelta(minutes=10),
            )
        results = self.parallel(2, lambda number: consume_login_link(raw_tokens[number], self.request()))
        self.assertEqual(results, [True, True])
        self.assertEqual(User.objects.filter(email="new@wdn.com.np").count(), 1)
        self.assertEqual(EmailToken.objects.filter(consumed_at__isnull=False).count(), 2)

    def test_same_login_token_can_be_consumed_once(self):
        raw = "one-valid-employee-token"
        EmailToken.objects.create(
            email="new@wdn.com.np",
            purpose="login",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        results = self.parallel(2, lambda _: consume_login_link(raw, self.request()))
        self.assertEqual(sorted(results), [False, True])

    def test_login_revalidation_rolls_back_account_if_token_becomes_unavailable(self):
        raw = "valid-before-user-creation-token"
        token = EmailToken.objects.create(
            email="new@wdn.com.np",
            purpose="login",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=10),
        )

        def create_then_expire(email):
            user = get_or_create_employee(email)
            EmailToken.objects.filter(pk=token.pk).update(expires_at=timezone.now() - timedelta(seconds=1))
            return user

        with patch("booking.services.email_login.get_or_create_employee", side_effect=create_then_expire):
            self.assertFalse(consume_login_link(raw, self.request()))
        self.assertFalse(User.objects.filter(email="new@wdn.com.np").exists())
        token.refresh_from_db()
        self.assertIsNone(token.consumed_at)

    def test_sign_in_and_user_deactivation_follow_same_lock_order(self):
        employee = User.objects.create_user("employee@wdn.com.np")
        raw = "existing-employee-login-token"
        EmailToken.objects.create(
            user=employee,
            email=employee.email,
            purpose="login",
            token_hash=hashlib.sha256(raw.encode()).hexdigest(),
            expires_at=timezone.now() + timedelta(minutes=10),
        )
        user_locked, token_read = Event(), Event()

        def deactivate():
            with transaction.atomic():
                user = User.objects.select_for_update().get(pk=employee.pk)
                user.is_active = False
                user.auth_version += 1
                user.save(update_fields=["is_active", "auth_version"])
                user_locked.set()
                if not token_read.wait(timeout=10):
                    raise TimeoutError("Sign-in did not reach token lookup")
                EmailToken.objects.filter(user=user, consumed_at__isnull=True).update(
                    consumed_at=timezone.now()
                )
            return "deactivated"

        def signal_token_read(execute, sql, params, many, context):
            result = execute(sql, params, many, context)
            if sql.lstrip().upper().startswith("SELECT") and '"email_tokens"' in sql:
                token_read.set()
            return result

        def sign_in():
            if not user_locked.wait(timeout=10):
                raise TimeoutError("Deactivation did not lock the account")
            with connection.execute_wrapper(signal_token_read):
                return consume_login_link(raw, self.request())

        results = self.parallel(2, lambda number: deactivate() if number == 0 else sign_in())
        self.assertEqual(results, ["deactivated", False])
        self.assertFalse(AuditEvent.objects.filter(action="employee_login").exists())

    def test_concurrent_password_setup_accepts_one_change(self):
        staff = User.objects.create_user("desk@wdn.com.np", PASSWORD, is_staff=True)
        uid = urlsafe_base64_encode(str(staff.pk).encode())
        url = reverse("staff-set-password", args=[uid, default_token_generator.make_token(staff)])

        def set_password(number):
            password = f"ChangedOfficePassphrase{number}2026!"
            return Client().post(url, {"password": password, "confirm": password}).status_code

        results = self.parallel(2, set_password)
        self.assertEqual(sorted(results), [302, 404])
        self.assertEqual(AuditEvent.objects.filter(action="staff_password_set").count(), 1)
