import hashlib
import hmac
import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth import authenticate, login
from django.core.mail import send_mail
from django.db import transaction
from django.utils import timezone

from booking.models import AuditEvent, EmailToken, User
from booking.services.email_login import normalized_employee_email


def _code_hash(user_id, code):
    return hmac.new(settings.SECRET_KEY.encode(), f"staff:{user_id}:{code}".encode(), hashlib.sha256).hexdigest()


def start_staff_login(email, password, request):
    email = normalized_employee_email(email or "")
    if not email:
        return False
    key = hashlib.sha256(f"{email}:{request.META.get('REMOTE_ADDR', '')}".encode()).hexdigest()
    recent_failures = AuditEvent.objects.filter(action="staff_password_failed", created_at__gte=timezone.now() - timedelta(minutes=15), details__key=key).count()
    if recent_failures >= 5:
        return False
    user = authenticate(request, username=email, password=password)
    if user is None or not user.is_active or not user.is_staff:
        AuditEvent.objects.create(action="staff_password_failed", outcome="denied", details={"key": key})
        return False
    now = timezone.now()
    EmailToken.objects.filter(user=user, purpose=EmailToken.Purpose.STAFF, consumed_at__isnull=True).update(consumed_at=now)
    code = f"{secrets.randbelow(100_000_000):08d}"
    token = EmailToken.objects.create(user=user, email=user.email, purpose=EmailToken.Purpose.STAFF, token_hash=_code_hash(user.pk, code), expires_at=now + timedelta(minutes=10))
    try:
        send_mail("Your WDN staff sign-in code", f"Your one-time staff sign-in code is {code}. It expires in 10 minutes. If you did not request it, contact IT.", settings.DEFAULT_FROM_EMAIL, [user.email], fail_silently=False)
    except Exception:
        EmailToken.objects.filter(pk=token.pk).update(consumed_at=timezone.now())
        return False
    request.session["pending_staff_token_id"] = token.pk
    request.session["staff_code_attempts"] = 0
    return True


@transaction.atomic
def finish_staff_login(code, request):
    token_id = request.session.get("pending_staff_token_id")
    if not token_id or not code or len(code) != 8 or not code.isdigit():
        return False
    token = EmailToken.objects.select_for_update(of=("self",)).select_related("user").filter(pk=token_id, purpose=EmailToken.Purpose.STAFF).first()
    if token is None or token.consumed_at or token.expires_at <= timezone.now() or not token.user.is_active or not token.user.is_staff:
        return False
    attempts = request.session.get("staff_code_attempts", 0) + 1
    request.session["staff_code_attempts"] = attempts
    if attempts > 5 or not hmac.compare_digest(token.token_hash, _code_hash(token.user_id, code)):
        if attempts >= 5:
            token.consumed_at = timezone.now()
            token.save(update_fields=["consumed_at"])
            request.session.pop("pending_staff_token_id", None)
        return False
    token.consumed_at = timezone.now()
    token.save(update_fields=["consumed_at"])
    login(request, token.user, backend="django.contrib.auth.backends.ModelBackend")
    request.session["staff_verified"] = True
    request.session.set_expiry(8 * 60 * 60)
    request.session.pop("pending_staff_token_id", None)
    request.session.pop("staff_code_attempts", None)
    AuditEvent.objects.create(actor=token.user, action="staff_login", outcome="success")
    return True
