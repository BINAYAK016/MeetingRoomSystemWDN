import hashlib
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import login
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.core.validators import validate_email
from django.db import transaction
from django.urls import reverse
from django.utils import timezone

from booking.models import AuditEvent, EmailToken, User


logger = logging.getLogger(__name__)
TOKEN_LIFETIME = timedelta(minutes=15)
REQUEST_WINDOW = timedelta(minutes=15)
MAX_REQUESTS_PER_ADDRESS = 3


def normalized_employee_email(value):
    email = value.strip().lower()
    try:
        validate_email(email)
    except ValidationError:
        return None
    parts = email.rsplit("@", 1)
    if len(parts) != 2 or parts[1] not in settings.EMPLOYEE_EMAIL_DOMAINS:
        return None
    return email


def request_login_link(email, request):
    email = normalized_employee_email(email)
    if email is None:
        return False

    existing = User.objects.filter(email__iexact=email).first()
    if existing is not None and not existing.is_active:
        return False

    now = timezone.now()
    recent = EmailToken.objects.filter(
        purpose=EmailToken.Purpose.LOGIN,
        email=email,
        created_at__gte=now - REQUEST_WINDOW,
    ).count()
    if recent >= MAX_REQUESTS_PER_ADDRESS:
        return False

    raw_token = secrets.token_urlsafe(32)
    token = EmailToken.objects.create(
        user=existing,
        email=email,
        purpose=EmailToken.Purpose.LOGIN,
        token_hash=hashlib.sha256(raw_token.encode()).hexdigest(),
        expires_at=now + TOKEN_LIFETIME,
    )
    link = request.build_absolute_uri(reverse("login-link", args=[raw_token]))
    try:
        send_mail(
            "Your WDN meeting room sign-in link",
            f"Use this link to sign in to the WDN meeting room system:\n\n{link}\n\n"
            "This link expires in 15 minutes and works once. If you did not request it, ignore this message.",
            settings.DEFAULT_FROM_EMAIL,
            [email],
            fail_silently=False,
        )
    except Exception as exc:
        EmailToken.objects.filter(pk=token.pk).update(consumed_at=timezone.now())
        logger.error("Sign-in email delivery failed (%s)", type(exc).__name__)
        return False
    return True


@transaction.atomic
def consume_login_link(raw_token, request):
    if not raw_token or len(raw_token) > 128:
        return False
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    token = (
        EmailToken.objects.select_for_update()
        .filter(token_hash=token_hash, purpose=EmailToken.Purpose.LOGIN)
        .first()
    )
    now = timezone.now()
    if token is None or token.consumed_at is not None or token.expires_at <= now:
        return False
    email = normalized_employee_email(token.email)
    if email is None:
        return False

    user = User.objects.filter(email__iexact=email).first()
    if user is not None and not user.is_active:
        return False
    if user is None:
        user = User.objects.create_user(email)

    token.consumed_at = now
    token.user = user
    token.save(update_fields=["consumed_at", "user"])
    # Staff administration will require its own verification gate in a later module.
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["staff_verified"] = False
    AuditEvent.objects.create(actor=user, action="employee_login", outcome="success")
    return True
