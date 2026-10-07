import logging
import re
import uuid

from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.db import InterfaceError, OperationalError
from django.utils.cache import add_never_cache_headers

from booking.logging import safe_exception_context

logger = logging.getLogger(__name__)


class ApplicationSafetyMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def _unavailable(self, request, exception):
        from booking.error_views import unavailable

        logger.error(
            "Database operation unavailable %s",
            safe_exception_context((type(exception), exception, exception.__traceback__)),
        )
        return unavailable(request)

    def __call__(self, request):
        reference = request.META.get("HTTP_X_REQUEST_ID", "")
        request.request_id = reference if re.fullmatch(r"[a-f0-9]{32}", reference) else uuid.uuid4().hex
        try:
            response = self.get_response(request)
            if response.status_code >= 400 or getattr(request, "user", AnonymousUser()).is_authenticated:
                add_never_cache_headers(response)
        except (InterfaceError, OperationalError) as exc:
            response = self._unavailable(request, exc)
        response["Content-Security-Policy"] = (
            "default-src 'self'; script-src 'self'; style-src 'self'; "
            "img-src 'self' data:; font-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"
        )
        response["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response["X-Request-ID"] = request.request_id
        return response

    def process_exception(self, request, exception):
        if isinstance(exception, (InterfaceError, OperationalError)):
            return self._unavailable(request, exception)
        return None


class LocalNullOriginMiddleware:
    """Allow the desktop in-app browser's opaque origin for loopback development.

    Django still validates the session-backed CSRF token. Production HTTPS never
    enters this branch, and Docker binds the development web port to loopback.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if (
            not settings.HTTPS_ENABLED
            and request.META.get("HTTP_ORIGIN") == "null"
            and request.get_host().split(":")[0] in {"localhost", "127.0.0.1"}
        ):
            request.META.pop("HTTP_ORIGIN")
        return self.get_response(request)
