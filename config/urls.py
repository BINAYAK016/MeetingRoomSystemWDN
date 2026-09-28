from django.db import connection
from django.http import HttpResponse
from django.urls import path

from booking import views


def healthcheck(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
    except Exception:
        return HttpResponse("unavailable", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("", views.home, name="home"),
    path("sign-in/", views.sign_in, name="sign-in"),
    path("sign-in/link/<str:token>/", views.login_link, name="login-link"),
    path("sign-in/confirm/", views.login_confirm, name="login-confirm"),
    path("sign-out/", views.sign_out, name="sign-out"),
    path("dev/mail/", views.dev_mail, name="dev-mail"),
    path("healthz/", healthcheck, name="healthcheck"),
]
