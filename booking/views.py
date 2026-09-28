from django.contrib.auth import logout
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from booking.services.email_login import consume_login_link, request_login_link


@require_GET
def home(request):
    return render(request, "booking/home.html")


@never_cache
@require_http_methods(["GET", "POST"])
def sign_in(request):
    if request.method == "POST":
        email = request.POST.get("email", "")
        if len(email) <= 254:
            request_login_link(email, request)
        return render(request, "booking/sign_in_sent.html")
    return render(request, "booking/sign_in.html")


@never_cache
@require_GET
def login_link(request, token):
    if len(token) > 128:
        return redirect("sign-in")
    request.session["pending_login_token"] = token
    return redirect("login-confirm")


@never_cache
@require_http_methods(["GET", "POST"])
def login_confirm(request):
    if request.method == "POST":
        token = request.session.pop("pending_login_token", None)
        if consume_login_link(token, request):
            return redirect("home")
        return render(request, "booking/login_confirm.html", {"invalid": True}, status=400)
    if not request.session.get("pending_login_token"):
        return redirect("sign-in")
    return render(request, "booking/login_confirm.html")


@require_POST
def sign_out(request):
    logout(request)
    return redirect("home")
