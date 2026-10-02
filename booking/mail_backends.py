from django.core.mail.backends.base import BaseEmailBackend


class MailUnavailable(RuntimeError):
    """Email is intentionally unavailable until deployment configuration is supplied."""


class DisabledEmailBackend(BaseEmailBackend):
    def send_messages(self, email_messages):
        if not email_messages:
            return 0
        raise MailUnavailable("Email is not configured")
