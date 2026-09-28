from django.conf import settings
from django.contrib.auth.tokens import default_token_generator
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.urls import reverse
from django.utils.http import urlsafe_base64_encode

from booking.models import AuditEvent, User
from booking.services.email_login import normalized_employee_email


class Command(BaseCommand):
    help = "Grant initial staff access and email a one-time password setup link."

    def add_arguments(self, parser):
        parser.add_argument("email")

    def handle(self, *args, **options):
        email = normalized_employee_email(options["email"])
        if not email:
            raise CommandError("Use a wdn.com.np email address")
        user, _ = User.objects.get_or_create(email=email)
        user.is_active = True
        user.is_staff = True
        user.save(update_fields=["is_active", "is_staff"])
        AuditEvent.objects.create(action="staff_bootstrap", target_type="user", target_id=user.pk, outcome="success")
        uid = urlsafe_base64_encode(str(user.pk).encode())
        token = default_token_generator.make_token(user)
        link = settings.PUBLIC_BASE_URL.rstrip("/") + reverse("staff-set-password", args=[uid, token])
        try:
            send_mail("Set your WDN staff password", f"Set your staff password using this link: {link}\nIf you did not expect this, contact IT.", settings.DEFAULT_FROM_EMAIL, [email])
        except Exception as exc:
            raise CommandError(f"Staff enabled, but setup email failed: {type(exc).__name__}") from exc
        self.stdout.write(self.style.SUCCESS(f"Staff enabled and setup email sent to {email}"))
