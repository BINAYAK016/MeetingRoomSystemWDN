import logging
import re
import sys
from importlib import import_module

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.contrib.messages.storage.cookie import CookieStorage
from django.db import InterfaceError, OperationalError
from django.http import HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


def _isolate_error_rendering(request):
    """Render server errors without reading broken authentication/session data."""
    request.user = AnonymousUser()
    # Preserve the client's existing cookie without loading or saving its DB row.
    request.session = import_module(settings.SESSION_ENGINE).SessionStore(
        session_key=request.COOKIES.get(settings.SESSION_COOKIE_NAME)
    )
    request.session._session_cache = {}
    request._messages = CookieStorage(request)


def _error(request, status, title, explanation):
    reference = getattr(request, "request_id", "")
    reference = reference if status >= 500 and re.fullmatch(r"[a-f0-9]{32}", reference) else ""
    try:
        return render(
            request,
            "booking/error.html",
            {
                "status": status,
                "error_title": title,
                "explanation": explanation,
                "request_reference": reference,
            },
            status=status,
        )
    except Exception as exc:
        # A missing static manifest or failed session must not break error handling.
        logging.getLogger(__name__).error("Error page rendering failed (%s)", type(exc).__name__)
        text = f"{title}\n{explanation}" + (f"\nSupport reference: {reference}" if reference else "")
        return HttpResponse(text, status=status, content_type="text/plain")


@never_cache
def bad_request(request, exception=None):
    return _error(
        request,
        400,
        "This request could not be processed.",
        "Return to the page and check the information you entered.",
    )


@never_cache
def permission_denied(request, exception=None):
    return _error(
        request,
        403,
        "You don’t have access to this page.",
        "Sign in with the correct company account or contact Front Desk.",
    )


@never_cache
def not_found(request, exception=None):
    return _error(
        request,
        404,
        "This page is unavailable.",
        "The address may be incorrect, or you may not have access to this record.",
    )


@never_cache
def server_error(request):
    exception = sys.exc_info()[1]
    if isinstance(exception, (InterfaceError, OperationalError)):
        return unavailable(request)
    _isolate_error_rendering(request)
    return _error(
        request, 500, "Something went wrong.", "Please try again later. Contact IT if the problem continues."
    )


@never_cache
def unavailable(request):
    _isolate_error_rendering(request)
    response = _error(
        request,
        503,
        "The service is temporarily unavailable.",
        "Please try again shortly. Your request was not completed; check your bookings before retrying.",
    )
    response["Retry-After"] = "30"
    return response
