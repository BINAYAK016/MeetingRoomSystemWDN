from booking.models import Department


def department_choices(current_department=""):
    """Offer active labels and allow an existing record to retain its saved label."""
    names = list(Department.objects.filter(is_active=True).values_list("name", flat=True))
    choices = [("", "Select department"), *((name, name) for name in names)]
    if current_department and current_department not in names:
        choices.append((current_department, f"{current_department} (current value)"))
    return choices


def active_department_name(name):
    """Prefill new meetings only from a department currently offered by staff."""
    return (
        Department.objects.filter(is_active=True, name__iexact=name).values_list("name", flat=True).first()
        or ""
    )
