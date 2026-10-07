from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from booking.models import AuditEvent, User


class ProfileForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "department"]


@login_required(login_url="sign-in")
@require_http_methods(["GET", "POST"])
def profile(request):
    form = ProfileForm(request.POST if request.method == "POST" else None, instance=request.user)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            # Updating only profile fields prevents a concurrent staff access change
            # from being overwritten by the user instance loaded at request start.
            User.objects.filter(pk=request.user.pk).update(**form.cleaned_data)
            AuditEvent.objects.create(
                actor=request.user,
                action="profile_updated",
                target_type="user",
                target_id=request.user.pk,
                outcome="success",
            )
        messages.success(request, "Your profile has been saved.")
        return redirect("profile")
    return render(request, "booking/profile.html", {"form": form})
