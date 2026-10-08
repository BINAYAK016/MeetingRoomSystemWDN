from django import forms


class HolidayUploadForm(forms.Form):
    file = forms.FileField(
        label="Holiday Excel file",
        widget=forms.FileInput(attrs={"accept": ".xlsx", "aria-describedby": "holiday-file-help"}),
        help_text="Excel .xlsx, up to 2 MiB and 1,000 holiday dates. Use the Holidays sheet with Date and Occasion headers.",
    )


class HolidayConfirmForm(forms.Form):
    preview_id = forms.CharField(max_length=64, widget=forms.HiddenInput)
    acknowledge_bookings = forms.BooleanField(
        required=False,
        label="I understand that existing meetings remain booked and need staff review.",
        error_messages={"required": "Acknowledge the existing meetings before importing these holidays."},
    )

    def __init__(self, *args, affected_bookings=0, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["acknowledge_bookings"].required = affected_bookings > 0
