import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def safe_subject(value):
    return " ".join(value.split())[:240]


def deliver_mail(subject, body, recipients):
    """Require the backend to accept the message; never log its sensitive content."""
    try:
        delivered = send_mail(
            safe_subject(subject), body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False
        )
        if delivered != 1:
            raise RuntimeError("Email backend did not accept the message")
    except Exception as exc:
        logger.warning("Email delivery failed (%s)", type(exc).__name__)
        raise
    return delivered
