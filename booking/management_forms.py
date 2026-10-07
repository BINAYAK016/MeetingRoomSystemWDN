from django import forms

from booking.services.email_login import employee_email_domain_label, normalized_employee_email


class UserAccessForm(forms.Form):
    email = forms.EmailField(max_length=254, label="Company email")
    first_name = forms.CharField(max_length=150, required=False)
    last_name = forms.CharField(max_length=150, required=False)
    department = forms.CharField(max_length=120, required=False)
    is_active = forms.BooleanField(required=False, initial=True, label="Active account")
    is_staff = forms.BooleanField(required=False, label="Front Desk / Administrator access")

    def clean_email(self):
        email = normalized_employee_email(self.cleaned_data["email"])
        if not email:
            raise forms.ValidationError(f"Use a company email address at {employee_email_domain_label()}.")
        return email
