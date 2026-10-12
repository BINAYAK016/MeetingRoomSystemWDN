import logging
from email.mime.image import MIMEImage
from pathlib import Path

from django.conf import settings
from django.core.mail import EmailMultiAlternatives, send_mail
from django.core.mail.message import SafeMIMEMultipart, SafeMIMEText

from booking.services.email_templates import EMAIL_LOGO_CID

logger = logging.getLogger(__name__)


class CalendarEmail(EmailMultiAlternatives):
    """Plain, logo-related HTML and calendar are sibling MIME alternatives."""

    def _create_alternatives(self, body_msg):
        encoding = self.encoding or settings.DEFAULT_CHARSET
        message = SafeMIMEMultipart(_subtype="alternative", encoding=encoding)
        message.attach(body_msg)
        for alternative in self.alternatives:
            part = self._create_mime_attachment(alternative.content, alternative.mimetype)
            if alternative.mimetype == "text/html":
                related = SafeMIMEMultipart(_subtype="related", encoding=encoding)
                related.attach(part)
                related.attach(self.inline_logo)
                message.attach(related)
            else:
                message.attach(part)
        calendar = SafeMIMEText(self.calendar_body, "calendar", encoding)
        calendar.set_param("method", self.calendar_method)
        calendar.set_param("name", "invitation.ics")
        calendar.add_header("Content-Disposition", "inline", filename="invitation.ics")
        message.attach(calendar)
        return message


def safe_subject(value):
    return " ".join(value.split())[:240]


def deliver_mail(
    subject,
    body,
    recipients,
    *,
    html_body=None,
    calendar_body=None,
    calendar_method=None,
    from_email=None,
    message_id=None,
):
    """Require the backend to accept the message; never log its sensitive content."""
    try:
        sender = from_email or settings.DEFAULT_FROM_EMAIL
        if html_body is None and calendar_body is None:
            # Retain the plain-text interface for operational commands and integrations.
            delivered = send_mail(safe_subject(subject), body, sender, recipients, fail_silently=False)
        else:
            if calendar_body is not None and calendar_method not in {"REQUEST", "CANCEL"}:
                raise ValueError("Unsupported calendar method")
            message_class = CalendarEmail if calendar_body is not None else EmailMultiAlternatives
            message = message_class(
                safe_subject(subject),
                body,
                sender,
                recipients,
                headers={"Message-ID": message_id} if message_id else None,
            )
            if html_body is not None:
                message.attach_alternative(html_body, "text/html")
            # Local, inline artwork avoids external image downloads or tracking pixels.
            logo = Path(settings.BASE_DIR) / "booking/static/booking/transgate-email-logo.png"
            image = MIMEImage(logo.read_bytes(), _subtype="png")
            image.add_header("Content-ID", f"<{EMAIL_LOGO_CID}>")
            image.add_header("Content-Disposition", "inline", filename="transgate.png")
            if calendar_body is not None:
                message.calendar_body = calendar_body
                message.calendar_method = calendar_method
                message.inline_logo = image
            else:
                message.attach(image)
                message.mixed_subtype = "related"
            delivered = message.send(fail_silently=False)
        if delivered != 1:
            raise RuntimeError("Email backend did not accept the message")
    except Exception as exc:
        logger.warning("Email delivery failed (%s)", type(exc).__name__)
        raise
    return delivered
