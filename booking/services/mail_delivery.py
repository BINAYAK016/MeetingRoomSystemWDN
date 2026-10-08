import logging
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail

from booking.services.email_templates import EMAIL_LOGO_CID

logger = logging.getLogger(__name__)


def safe_subject(value):
    return " ".join(value.split())[:240]


def deliver_mail(subject, body, recipients, *, html_body=None):
    """Require the backend to accept the message; never log its sensitive content."""
    try:
        if html_body is None:
            # Retain the plain-text interface for operational commands and integrations.
            delivered = send_mail(
                safe_subject(subject), body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False
            )
        else:
            message = EmailMultiAlternatives(
                safe_subject(subject), body, settings.DEFAULT_FROM_EMAIL, recipients
            )
            message.attach_alternative(html_body, "text/html")
            # Local, inline artwork avoids external image downloads or tracking pixels.
            logo = Path(settings.BASE_DIR) / "booking/static/booking/transgate-email-logo.png"
            image = MIMEImage(logo.read_bytes(), _subtype="png")
            image.add_header("Content-ID", f"<{EMAIL_LOGO_CID}>")
            image.add_header("Content-Disposition", "inline", filename="transgate.png")
            message.attach(image)
            message.mixed_subtype = "related"
            delivered = message.send(fail_silently=False)
        if delivered != 1:
            raise RuntimeError("Email backend did not accept the message")
    except Exception as exc:
        logger.warning("Email delivery failed (%s)", type(exc).__name__)
        raise
    return delivered
