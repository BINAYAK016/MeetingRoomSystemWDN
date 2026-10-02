import hashlib
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.db import transaction
from django.utils import timezone
from django.views.decorators.debug import sensitive_variables

from booking.models import AuditEvent, EmailToken, User
from booking.services.auth_security import allow_auth_request
from booking.services.email_login import normalized_employee_email
from booking.services.mail_delivery import deliver_mail

logger = logging.getLogger(__name__)
MAX_CODE_ATTEMPTS = 5


@sensitive_variables("code", "value")
def _code_hash(user, code, token_id):
    value = f"staff:{user.pk}:{token_id}:{user.auth_version}:{user.password}:{code}"
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


@sensitive_variables("password", "code")
def start_staff_login(email, password, request):
    email = normalized_employee_email(email or "")
    if not email:
        return False
    if not allow_auth_request("staff_password", email, request, account_limit=5, ip_limit=30):
        return False
    if not isinstance(password, str) or not password or len(password) > 4096:
        return False
    user = authenticate(request, username=email, password=password)
    if user is None or not user.is_active or not user.is_staff:
        AuditEvent.objects.create(action="staff_password_failed", outcome="denied")
        logger.info("Staff password authentication denied")
        return False
    now = timezone.now()
    code = f"{secrets.randbelow(100_000_000):08d}"
    with transaction.atomic():
        current = User.objects.select_for_update().get(pk=user.pk)
        if not current.is_active or not current.is_staff or current.password != user.password:
            return False
        EmailToken.objects.filter(
            user=current, purpose=EmailToken.Purpose.STAFF, consumed_at__isnull=True
        ).update(consumed_at=now)
        token = EmailToken.objects.create(
            user=current,
            email=current.email,
            purpose=EmailToken.Purpose.STAFF,
            token_hash=secrets.token_hex(32),
            expires_at=now + timedelta(minutes=10),
        )
        token.token_hash = _code_hash(current, code, token.pk)
        token.save(update_fields=["token_hash"])
    try:
        deliver_mail(
            "Your WDN staff sign-in code",
            f"Your one-time staff sign-in code is {code}. It expires in 10 minutes. If you did not request it, contact IT.",
            [user.email],
        )
    except Exception as exc:
        EmailToken.objects.filter(pk=token.pk).update(consumed_at=timezone.now())
        logger.warning("Staff sign-in email delivery failed (%s)", type(exc).__name__)
        AuditEvent.objects.create(actor=user, action="staff_login_email_failed", outcome="failed")
        return False
    request.session.cycle_key()
    request.session["pending_staff_token_id"] = token.pk
    return True


@sensitive_variables("code")
@transaction.atomic
def finish_staff_login(code, request):
    token_id = request.session.get("pending_staff_token_id")
    if not token_id:
        return False
    initial = EmailToken.objects.filter(pk=token_id, purpose=EmailToken.Purpose.STAFF).first()
    if initial is None or initial.user_id is None:
        return False
    # All credential changes lock user before staff tokens to prevent deadlocks.
    user = User.objects.select_for_update().get(pk=initial.user_id)
    token = EmailToken.objects.select_for_update().get(pk=initial.pk)
    if token.consumed_at or token.expires_at <= timezone.now() or not user.is_active or not user.is_staff:
        request.session.pop("pending_staff_token_id", None)
        return False
    token.attempts += 1
    token.save(update_fields=["attempts"])
    valid_format = isinstance(code, str) and len(code) == 8 and code.isascii() and code.isdigit()
    if (
        token.attempts > MAX_CODE_ATTEMPTS
        or not valid_format
        or not hmac.compare_digest(token.token_hash, _code_hash(user, code, token.pk))
    ):
        if token.attempts >= MAX_CODE_ATTEMPTS:
            token.consumed_at = timezone.now()
            token.save(update_fields=["consumed_at"])
            request.session.pop("pending_staff_token_id", None)
        AuditEvent.objects.create(actor=user, action="staff_code_failed", outcome="denied")
        return False
    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])
    login(request, user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["staff_verified"] = True
    request.session["staff_auth_version"] = user.auth_version
    request.session.set_expiry(8 * 60 * 60)
    request.session.pop("pending_staff_token_id", None)
    request.session.pop("staff_code_attempts", None)
    AuditEvent.objects.create(actor=user, action="staff_login", outcome="success")
    return True
