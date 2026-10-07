from django.conf import settings

from booking.services.email_login import employee_email_domain_label


def employee_email_domains(request):
    """Keep displayed email eligibility aligned with the configured allowlist."""
    return {
        "employee_email_domain_label": employee_email_domain_label(),
        "employee_email_placeholder": f"you@{settings.EMPLOYEE_EMAIL_DOMAINS[0]}",
    }
