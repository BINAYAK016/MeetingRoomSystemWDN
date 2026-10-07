import hashlib
import logging
import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from booking.models import AuditEvent, EmailToken, User
from booking.services.auth_security import allow_auth_request
from booking.services.mail_delivery import deliver_mail

logger = logging.getLogger(__name__)
TOKEN_LIFETIME = timedelta(minutes=15)
MAX_REQUESTS_PER_ADDRESS = 3


def employee_email_domain_label():
    """Describe the current company-domain allowlist for UI and validation."""
    domains = [f"@{domain}" for domain in settings.EMPLOYEE_EMAIL_DOMAINS]
    if len(domains) <= 2:
        return " or ".join(domains)
    return ", ".join(domains[:-1]) + f", or {domains[-1]}"


def normalized_employee_email(value):
    if not isinstance(value, str) or len(value) > 254:
        return None
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return None
    parts = email.rsplit("@", 1)
    if len(parts) != 2 or parts[1] not in settings.EMPLOYEE_EMAIL_DOMAINS:
        return None
    return email


@sensitive_variables("raw_token")
def request_login_link(email, request):
    email = normalized_employee_email(email)
    if email is None:
        return False

    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None and not existing.is_active:
        return False

    now = timezone.now()
    if not allow_auth_request(
        "employee_link", email, request, account_limit=MAX_REQUESTS_PER_ADDRESS, ip_limit=20
    ):
        return False

    raw_token = secrets.token_urlsafe(32)
    token = EmailToken.objects.create(
        user=existing,
        email=email,
        purpose=EmailToken.Purpose.LOGIN,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=now + TOKEN_LIFETIME,
    )
    link = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("login-link", args=[raw_token])
    try:
        deliver_mail(
            "Your WDN meeting room sign-in link",
            f"Use this link to sign in to the WDN meeting room system:\n\n{link}\n\n"
            "This link expires in 15 minutes and works once. If you did not request it, ignore this message.",
            [email],
        )
    except Exception as exc:
        EmailToken.objects.filter(pk=token.pk).update(consumed_at=timezone.now())
        logger.error("Sign-in email delivery failed (%s)", type(exc).__name__)
        AuditEvent.objects.create(action="employee_login_email_failed", outcome="failed")
        return False
    return True


def get_or_create_employee(email):
    user = User.objects.filter(email__iexact=email).first()
    if user is not None:
        return user
    try:
        with transaction.atomic():
            return User.objects.create_user(email)
    except IntegrityError:
        user = User.objects.filter(email__iexact=email).first()
        if user is None:
            raise
        return user


class _UnavailableLoginLink(Exception):
    pass


@sensitive_variables("raw_token")
def consume_login_link(raw_token, request):
    if not isinstance(raw_token, str) or not raw_token or len(raw_token) > 128:
        return False
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    return consume_login_hash(token_hash, request)


def consume_login_hash(token_hash, request):
    """Consume the digest staged by the GET view; external links always use raw tokens."""
    if not isinstance(token_hash, str) or re.fullmatch(r"[0-9a-f]{64}", token_hash) is None:
        return False
    token = EmailToken.objects.filter(token_hash=token_hash, purpose=EmailToken.Purpose.LOGIN).first()
    now = timezone.now()
    if token is None or token.consumed_at is not None or token.expires_at <= now:
        return False
    email = normalized_employee_email(token.email)
    if email is None:
        return False

    try:
        with transaction.atomic():
            # Access changes and staff authentication lock User before EmailToken.
            # Recheck the nonlocking lookup after acquiring locks in that order.
            user = get_or_create_employee(email)
            user = User.objects.select_for_update().get(pk=user.pk)
            token = EmailToken.objects.select_for_update().get(pk=token.pk)
            now = timezone.now()
            if (
                not user.is_active
                or token.consumed_at is not None
                or token.expires_at <= now
                or token.purpose != EmailToken.Purpose.LOGIN
                or normalized_employee_email(token.email) != email
            ):
                # Roll back an account created while the token became unavailable.
                raise _UnavailableLoginLink
            token.consumed_at = now
            token.user = user
            token.save(update_fields=["consumed_at", "user"])
            login(request, user, backend="django.contrib.auth.backends.ModelBackend")
            request.session["staff_verified"] = False
            request.session.pop("staff_auth_version", None)
            request.session.set_expiry(8 * 60 * 60)
            AuditEvent.objects.create(actor=user, action="employee_login", outcome="success")
            return True
    except _UnavailableLoginLink:
        return False
