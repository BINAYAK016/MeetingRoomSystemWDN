from django.conf import settings


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
