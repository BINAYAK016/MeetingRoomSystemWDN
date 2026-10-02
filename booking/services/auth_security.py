import hashlib
import hmac
from datetime import timedelta
from ipaddress import ip_address, ip_network

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from booking.models import AuditEvent, AuthenticationThrottle

AUTH_WINDOW = timedelta(minutes=15)


def client_ip(request):
    """Use the proxy's overwritten header only on an explicitly trusted network."""
    remote = request.META.get("REMOTE_ADDR", "")
    try:
        address = ip_address(remote)
    except ValueError:
        return "unknown"
    trusted = getattr(settings, "AUTH_TRUSTED_PROXY_CIDRS", ())
    if isinstance(trusted, str):
        trusted = trusted.split(",")
    for cidr in trusted:
        try:
            network = ip_network(cidr.strip(), strict=False)
        except ValueError:
            continue
        if address in network:
            try:
                return str(ip_address(request.META.get("HTTP_X_REAL_IP", "")))
            except ValueError:
                return str(address)
    return str(address)


def identity_key(value):
    return hmac.new(settings.SECRET_KEY.encode(), value.encode(), hashlib.sha256).hexdigest()


def _locked_counter(purpose, value, now):
    key = identity_key(value)
    counter, _ = AuthenticationThrottle.objects.get_or_create(
        purpose=purpose,
        key=key,
        defaults={"window_started_at": now},
    )
    counter = AuthenticationThrottle.objects.select_for_update().get(pk=counter.pk)
    if counter.window_started_at + AUTH_WINDOW <= now:
        counter.window_started_at = now
        counter.attempts = 0
    return counter


@transaction.atomic
def allow_auth_request(purpose, email, request, *, account_limit, ip_limit):
    """Serialize counters across workers; an account limit also spans IP addresses."""
    now = timezone.now()
    # Lock the IP first, so blocked clients cannot fill the table with new emails.
    source = _locked_counter(f"{purpose}_ip", client_ip(request), now)
    if source.attempts >= ip_limit:
        AuditEvent.objects.create(
            action="auth_rate_limited", outcome="denied", details={"purpose": purpose, "scope": "ip"}
        )
        return False
    source.attempts += 1
    source.save(update_fields=["attempts", "window_started_at"])
    account = _locked_counter(f"{purpose}_account", email, now)
    if account.attempts >= account_limit:
        AuditEvent.objects.create(
            action="auth_rate_limited", outcome="denied", details={"purpose": purpose, "scope": "account"}
        )
        return False
    account.attempts += 1
    account.save(update_fields=["attempts", "window_started_at"])
    return True


def staff_session_verified(request):
    user = request.user
    return (
        user.is_authenticated
        and user.is_active
        and user.is_staff
        and request.session.get("staff_verified") is True
        and request.session.get("staff_auth_version") == user.auth_version
    )
