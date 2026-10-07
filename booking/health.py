import logging
from datetime import timedelta

from django.conf import settings
from django.db import connection
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from booking.models import WorkerHeartbeat

logger = logging.getLogger(__name__)


def worker_is_healthy():
    heartbeat = WorkerHeartbeat.objects.filter(pk=1).first()
    return bool(
        heartbeat
        and heartbeat.last_success_at
        and heartbeat.last_success_at >= timezone.now() - timedelta(seconds=120)
    )


@never_cache
@require_GET
def liveness(request):
    return HttpResponse("ok", content_type="text/plain")


@never_cache
@require_GET
def readiness(request):
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        worker_ok = worker_is_healthy()
    except Exception as exc:
        logger.error("Readiness database check failed (%s)", type(exc).__name__)
        return JsonResponse({"status": "unavailable", "database": "unavailable"}, status=503)
    if not worker_ok:
        return JsonResponse({"status": "unavailable", "database": "ok", "worker": "unavailable"}, status=503)
    email = "unavailable"
    if settings.EMAIL_READY:
        email = "local-file" if settings.MAIL_MODE == "file" else "configured"
    return JsonResponse({"status": "ok", "database": "ok", "worker": "ok", "email": email})
