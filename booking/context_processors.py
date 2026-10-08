from django.conf import settings

from booking.services.auth_security import staff_session_verified
from booking.services.email_login import employee_email_domain_label


def employee_email_domains(request):
    """Keep displayed email eligibility aligned with the configured allowlist."""
    return {
        "employee_email_domain_label": employee_email_domain_label(),
        "employee_email_placeholder": f"you@{settings.EMPLOYEE_EMAIL_DOMAINS[0]}",
        "workspace_staff_verified": (
            hasattr(request, "user") and hasattr(request, "session") and staff_session_verified(request)
        ),
    }
