from django import forms

from booking.department_choices import department_choices
from booking.models import Department
from booking.services.email_login import employee_email_domain_label, normalized_employee_email


class DepartmentForm(forms.ModelForm):
    class Meta:
        model = Department
        fields = ["name", "is_active"]
        labels = {"name": "Department name", "is_active": "Available for new bookings"}
        help_texts = {
            "name": "Renaming a department keeps the department text on existing meetings unchanged.",
            "is_active": "Clear this to hide the department from new bookings. Existing meetings are kept.",
        }

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        duplicates = Department.objects.filter(name__iexact=name)
        if self.instance.pk:
            duplicates = duplicates.exclude(pk=self.instance.pk)
        if duplicates.exists():
            raise forms.ValidationError(
                "A department with this name already exists, including inactive departments."
            )
        return name


class UserAccessForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Company email")
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    department = forms.ChoiceField(required=False)
    is_active = forms.BooleanField(required=False, initial=True, label="Active account")
    is_staff = forms.BooleanField(required=False, label="Front Desk / Administrator access")

    def __init__(self, *args, current_department="", **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["department"].choices = department_choices(current_department)

    def clean_email(self):
        email = normalized_employee_email(self.cleaned_data["email"])
        if not email:
            raise forms.ValidationError(f"Use a company email address at {employee_email_domain_label()}.")
        return email
