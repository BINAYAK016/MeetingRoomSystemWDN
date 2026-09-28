import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from booking.models import BookingPolicy, Reservation, Room
from booking.services.email_login import normalized_employee_email


class BookingForm(forms.Form):
    room = forms.ModelChoiceField(queryset=Room.objects.none())
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time", "step": "900"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time", "step": "900"}))
    title = forms.CharField(max_length=200)
    description = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    meeting_type = forms.ChoiceField(choices=Reservation.MeetingType.choices)
    guest_company_name = forms.CharField(max_length=200, required=False)
    external_attendee_count = forms.IntegerField(min_value=0, max_value=500, initial=0)
    department = forms.CharField(max_length=120, required=False)
    attendees = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}), help_text="One email address per line or separated by commas.")
    refreshments_requested = forms.BooleanField(required=False)
    front_desk_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    recurrence = forms.ChoiceField(choices=[("none", "One meeting"), ("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")], initial="none")
    until_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    organizer_email = forms.EmailField(required=False, help_text="Staff only: book on behalf of a WDN employee.")
    override_reason = forms.CharField(max_length=500, required=False, widget=forms.Textarea(attrs={"rows": 2}), help_text="Staff only: required when overriding booking rules.")

    def __init__(self, *args, staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff = staff
        self.fields["room"].queryset = Room.objects.filter(is_active=True).order_by("location", "floor", "name")
        if not staff:
            self.fields.pop("organizer_email")
            self.fields.pop("override_reason")

    def clean_attendees(self):
        raw = self.cleaned_data["attendees"]
        addresses = []
        for item in re.split(r"[\s,;]+", raw.strip()):
            if not item:
                continue
            email = item.lower()
            try:
                validate_email(email)
            except ValidationError as exc:
                raise forms.ValidationError(f"Invalid attendee email: {item}") from exc
            if email not in addresses:
                addresses.append(email)
        if len(addresses) > 50:
            raise forms.ValidationError("A booking can have at most 50 email attendees")
        return addresses

    def clean_organizer_email(self):
        value = self.cleaned_data.get("organizer_email", "")
        if value and not normalized_employee_email(value):
            raise forms.ValidationError("Use a wdn.com.np employee address")
        return normalized_employee_email(value) if value else ""

    def clean(self):
        data = super().clean()
        if data.get("meeting_type") == Reservation.MeetingType.EXTERNAL and not data.get("guest_company_name"):
            self.add_error("guest_company_name", "Enter the guest company name")
        if "recurrence" in self.fields and data.get("recurrence") != "none" and not data.get("until_date"):
            self.add_error("until_date", "Choose the last date for this series")
        if data.get("until_date") and data.get("date") and data["until_date"] < data["date"]:
            self.add_error("until_date", "The last date cannot be before the first date")
        return data


class RoomForm(forms.ModelForm):
    facilities_text = forms.CharField(required=False, help_text="One facility per line or separated by commas.", widget=forms.Textarea(attrs={"rows": 3}))

    class Meta:
        model = Room
        fields = ["name", "location", "floor", "capacity", "description", "instructions", "is_active"]
        widgets = {"description": forms.Textarea(attrs={"rows": 3}), "instructions": forms.Textarea(attrs={"rows": 3})}


class RoomBlockForm(forms.Form):
    room = forms.ModelChoiceField(queryset=Room.objects.none())
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    start_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time", "step": "900"}))
    end_time = forms.TimeField(widget=forms.TimeInput(attrs={"type": "time", "step": "900"}))
    block_reason = forms.CharField(max_length=240)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["room"].queryset = Room.objects.filter(is_active=True)


class PolicyForm(forms.ModelForm):
    class Meta:
        model = BookingPolicy
        fields = ["opens_at", "closes_at", "minimum_minutes", "maximum_minutes", "slot_minutes", "gap_minutes", "advance_days", "check_in_minutes"]
        widgets = {"opens_at": forms.TimeInput(attrs={"type": "time"}), "closes_at": forms.TimeInput(attrs={"type": "time"})}

    def clean(self):
        data = super().clean()
        if data.get("opens_at") and data.get("closes_at") and data["opens_at"] >= data["closes_at"]:
            self.add_error("closes_at", "Closing time must be after opening time")
        if data.get("minimum_minutes") and data.get("maximum_minutes") and data["minimum_minutes"] > data["maximum_minutes"]:
            self.add_error("maximum_minutes", "Maximum duration must be at least the minimum")
        return data
