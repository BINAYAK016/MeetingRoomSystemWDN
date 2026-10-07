import hashlib
import re
from pathlib import Path

from django.conf import settings
from django.contrib.auth import logout
from django.http import Http404
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from booking.models import BookingPolicy, Reservation, Room
from booking.services.email_login import consume_login_hash, request_login_link


@never_cache
@require_GET
def home(request):
    context = {}
    if request.user.is_authenticated:
        context["rooms"] = Room.objects.filter(is_active=True).order_by("location", "floor", "name")[:6]
        context["room_count"] = Room.objects.filter(is_active=True).count()
        context["policy"] = BookingPolicy.objects.filter(pk=1).first()
        context["upcoming_count"] = Reservation.objects.filter(
            organizer=request.user,
            status__in=[Reservation.Status.APPROVED, Reservation.Status.CHECKED_IN],
            starts_at__gte=timezone.now(),
        ).count()
        context["pending_count"] = Reservation.objects.filter(
            organizer=request.user, status=Reservation.Status.PENDING
        ).count()
    return render(request, "booking/home.html", context)


@never_cache
@require_http_methods(["GET", "POST"])
def sign_in(request):
    context = {
        "local_mail": local_mail_available(request),
        "email_unavailable": settings.EMAIL_BACKEND == "booking.mail_backends.DisabledEmailBackend",
    }
    if request.method == "POST":
        email = request.POST.get("email", "")
        if len(email) <= 254:
            request_login_link(email, request)
        return render(request, "booking/sign_in_sent.html", context)
    return render(request, "booking/sign_in.html", context)


@never_cache
@sensitive_variables("token")
@require_GET
def login_link(request, token):
    if len(token) > 128:
        return redirect("sign-in")
    request.session["pending_login_token"] = hashlib.sha256(token.encode()).hexdigest()
    return redirect("login-confirm")


@never_cache
@sensitive_variables("token")
@require_http_methods(["GET", "POST"])
def login_confirm(request):
    if request.method == "POST":
        token = request.session.pop("pending_login_token", None)
        if consume_login_hash(token, request):
            return redirect("home")
        return render(request, "booking/login_confirm.html", {"invalid": True}, status=400)
    if not request.session.get("pending_login_token"):
        return redirect("sign-in")
    return render(request, "booking/login_confirm.html")


@require_POST
def sign_out(request):
    logout(request)
    return redirect("home")


def local_mail_available(request):
    return (
        settings.MAIL_MODE == "file"
        and not settings.HTTPS_ENABLED
        and request.get_host().split(":")[0] in {"localhost", "127.0.0.1"}
    )


@never_cache
@require_GET
def dev_mail(request):
    if not local_mail_available(request):
        raise Http404
    mail_items = []
    mail_dir = Path(settings.EMAIL_FILE_PATH)
    for mail_file in sorted(mail_dir.glob("*.log"), key=lambda item: item.stat().st_mtime, reverse=True)[:10]:
        body = mail_file.read_text(encoding="utf-8", errors="replace")
        recipient = re.search(r"^To: (.+)$", body, re.MULTILINE)
        link = re.search(
            r"^https?://\S+/(?:sign-in/link|check-in/link|staff/set-password)/\S+", body, re.MULTILINE
        )
        code = re.search(r"one-time staff sign-in code is (\d{8})", body)
        if link or code:
            mail_items.append(
                {
                    "recipient": recipient.group(1) if recipient else "WDN employee",
                    "link": link.group(0) if link else "",
                    "code": code.group(1) if code else "",
                }
            )
    return render(request, "booking/dev_mail.html", {"mail_items": mail_items})


@never_cache
def csrf_failure(request, reason=""):
    return render(request, "booking/csrf_failure.html", status=403)
