import re

from django import forms
from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from booking.models import BookingPolicy, Reservation, Room
from booking.services.email_login import employee_email_domain_label, normalized_employee_email


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
    attendees = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={"rows": 3}),
        help_text="One email address per line or separated by commas.",
    )
    refreshments_requested = forms.BooleanField(required=False)
    front_desk_notes = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    recurrence = forms.ChoiceField(
        choices=[("none", "One meeting"), ("daily", "Daily"), ("weekly", "Weekly"), ("monthly", "Monthly")],
        initial="none",
    )
    until_date = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    organizer_email = forms.EmailField(
        required=False, help_text="Staff only: book on behalf of a company employee."
    )
    override_reason = forms.CharField(
        max_length=500,
        required=False,
        widget=forms.Textarea(attrs={"rows": 2}),
        help_text="Staff only: required when overriding booking rules.",
    )

    def __init__(self, *args, staff=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.staff = staff
        self.fields["room"].queryset = Room.objects.filter(is_active=True).order_by(
            "location", "floor", "name"
        )
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
            raise forms.ValidationError(f"Use a company email address at {employee_email_domain_label()}.")
        return normalized_employee_email(value) if value else ""

    def clean(self):
        data = super().clean()
        if data.get("meeting_type") == Reservation.MeetingType.EXTERNAL and not data.get(
            "guest_company_name"
        ):
            self.add_error("guest_company_name", "Enter the guest company name")
        if "recurrence" in self.fields and data.get("recurrence") != "none" and not data.get("until_date"):
            self.add_error("until_date", "Choose the last date for this series")
        if data.get("until_date") and data.get("date") and data["until_date"] < data["date"]:
            self.add_error("until_date", "The last date cannot be before the first date")
        return data


class RoomForm(forms.ModelForm):
    facilities_text = forms.CharField(
        max_length=10000,
        required=False,
        help_text="One facility per line or separated by commas.",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def clean_facilities_text(self):
        names = []
        seen = set()
        for item in re.split(r"[\n,;]+", self.cleaned_data["facilities_text"]):
            name = item.strip()
            if not name:
                continue
            if len(name) > 120:
                raise forms.ValidationError("Each facility name must have at most 120 characters")
            if name.casefold() not in seen:
                names.append(name)
                seen.add(name.casefold())
        if len(names) > 50:
            raise forms.ValidationError("A room can have at most 50 facilities")
        return "\n".join(names)

    class Meta:
        model = Room
        fields = ["name", "location", "floor", "capacity", "description", "instructions", "is_active"]
        widgets = {
            "description": forms.Textarea(attrs={"rows": 3}),
            "instructions": forms.Textarea(attrs={"rows": 3}),
        }


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
        fields = [
            "opens_at",
            "closes_at",
            "minimum_minutes",
            "maximum_minutes",
            "slot_minutes",
            "gap_minutes",
            "advance_days",
            "check_in_minutes",
        ]
        widgets = {
            "opens_at": forms.TimeInput(attrs={"type": "time"}),
            "closes_at": forms.TimeInput(attrs={"type": "time"}),
        }

    def clean(self):
        data = super().clean()
        if data.get("opens_at") and data.get("closes_at") and data["opens_at"] >= data["closes_at"]:
            self.add_error("closes_at", "Closing time must be after opening time")
        if (
            data.get("minimum_minutes")
            and data.get("maximum_minutes")
            and data["minimum_minutes"] > data["maximum_minutes"]
        ):
            self.add_error("maximum_minutes", "Maximum duration must be at least the minimum")
        limits = {
            "minimum_minutes": (1, 1440),
            "maximum_minutes": (1, 1440),
            "slot_minutes": (1, 60),
            "gap_minutes": (0, 120),
            "advance_days": (1, 366),
            "check_in_minutes": (1, 1440),
        }
        for field, (minimum, maximum) in limits.items():
            value = data.get(field)
            if value is not None and not minimum <= value <= maximum:
                self.add_error(field, f"Use a value between {minimum} and {maximum}")
        if (
            data.get("check_in_minutes")
            and data.get("minimum_minutes")
            and data["check_in_minutes"] > data["minimum_minutes"]
        ):
            self.add_error("check_in_minutes", "Check-in must close within the shortest permitted meeting")
        if data.get("opens_at") and data.get("closes_at") and data.get("minimum_minutes"):
            office_minutes = (data["closes_at"].hour * 60 + data["closes_at"].minute) - (
                data["opens_at"].hour * 60 + data["opens_at"].minute
            )
            if office_minutes > 0 and data["minimum_minutes"] > office_minutes:
                self.add_error("minimum_minutes", "The minimum meeting must fit within office hours")
        step = data.get("slot_minutes")
        if step and 1 <= step <= 60:
            for field in ("minimum_minutes", "maximum_minutes"):
                if data.get(field) and data[field] % step:
                    self.add_error(field, "Meeting limits must use whole booking increments")
            for field in ("opens_at", "closes_at"):
                value = data.get(field)
                if value and (value.second or value.microsecond or (value.hour * 60 + value.minute) % step):
                    self.add_error(field, "Office hours must align with booking increments")
        return data
