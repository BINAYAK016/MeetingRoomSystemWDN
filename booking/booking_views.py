from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods

from booking.forms import BookingForm
from booking.models import BookingPolicy, Reservation, Room
from booking.services.bookings import BookingError, cancel_booking, create_booking, update_booking
from booking.services.checkin import CheckInError, confirm_checkin
from booking.services.notifications import queue_conflict_notice


def _staff(request):
    return request.user.is_authenticated and request.user.is_staff and request.session.get("staff_verified") is True


@login_required(login_url="sign-in")
@require_GET
def room_list(request):
    rooms = Room.objects.filter(is_active=True).prefetch_related("facilities").order_by("location", "floor", "name")
    capacity = request.GET.get("capacity", "")[:5]
    if capacity.isdigit():
        rooms = rooms.filter(capacity__gte=int(capacity))
    return render(request, "booking/rooms.html", {"rooms": rooms, "capacity": capacity})


@login_required(login_url="sign-in")
@require_GET
def room_detail(request, room_id):
    room = get_object_or_404(Room.objects.prefetch_related("facilities"), pk=room_id, is_active=True)
    return render(request, "booking/room_detail.html", {"room": room})


@login_required(login_url="sign-in")
@require_GET
def calendar_view(request):
    policy = BookingPolicy.objects.get(pk=1)
    try:
        selected = datetime.strptime(request.GET.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        selected = timezone.localdate()
    if abs((selected - timezone.localdate()).days) > 366:
        selected = timezone.localdate()
    view = request.GET.get("view", "day")
    if view not in ("day", "week", "month"):
        view = "day"
    if view == "month" and not _staff(request):
        view = "week"
    rooms = list(Room.objects.filter(is_active=True).order_by("location", "floor", "name"))
    if view == "week":
        first = selected - timedelta(days=selected.weekday())
        days = [first + timedelta(days=i) for i in range(7)]
    elif view == "month":
        first = selected.replace(day=1)
        days = [first + timedelta(days=i) for i in range(35) if (first + timedelta(days=i)).month == first.month]
    else:
        days = [selected]
    last = days[-1] + timedelta(days=1)
    bookings = list(Reservation.objects.filter(
        starts_at__lt=datetime.combine(last, datetime.min.time(), ZoneInfo("Asia/Kathmandu")),
        ends_at__gt=datetime.combine(days[0], datetime.min.time(), ZoneInfo("Asia/Kathmandu")),
        status__in=[Reservation.Status.CONFIRMED, Reservation.Status.CHECKED_IN, Reservation.Status.COMPLETED, Reservation.Status.BLOCKED],
    ).select_related("room"))
    cutoff = timezone.now() - timedelta(minutes=policy.check_in_minutes)
    bookings = [item for item in bookings if not (item.status == Reservation.Status.CONFIRMED and item.starts_at <= cutoff)]
    if view == "day":
        slots = []
        cursor = datetime.combine(selected, policy.opens_at, ZoneInfo("Asia/Kathmandu"))
        end = datetime.combine(selected, policy.closes_at, ZoneInfo("Asia/Kathmandu"))
        while cursor < end:
            slot_end = cursor + timedelta(minutes=policy.slot_minutes)
            cells = []
            for room in rooms:
                occupying = next((item for item in bookings if item.room_id == room.pk and item.occupied_from < slot_end and item.occupied_until > cursor), None)
                cells.append({"room": room, "occupied": occupying, "own": occupying and occupying.organizer_id == request.user.pk})
            slots.append({"time": cursor, "cells": cells})
            cursor = slot_end
        return render(request, "booking/calendar.html", {"view": view, "selected": selected, "rooms": rooms, "slots": slots, "policy": policy})
    day_rows = []
    for day in days:
        day_rows.append({"date": day, "cells": [
            {"room": room, "count": sum(1 for item in bookings if item.room_id == room.pk and timezone.localtime(item.starts_at).date() == day)}
            for room in rooms
        ]})
    return render(request, "booking/calendar.html", {"view": view, "selected": selected, "rooms": rooms, "day_rows": day_rows, "policy": policy})


@login_required(login_url="sign-in")
@require_http_methods(["GET", "POST"])
def booking_new(request):
    staff = _staff(request)
    initial = {"room": request.GET.get("room"), "date": request.GET.get("date"), "start_time": request.GET.get("start"), "meeting_type": "internal", "recurrence": "none"}
    form = BookingForm(request.POST or None, initial=initial if request.method == "GET" else None, staff=staff)
    if request.method == "POST" and form.is_valid():
        try:
            bookings = create_booking(form.cleaned_data, actor=request.user, staff=staff)
        except BookingError as exc:
            form.add_error(None, str(exc))
            if "unavailable" in str(exc).lower():
                queue_conflict_notice(request.user.email, form.cleaned_data["room"].name, form.cleaned_data["date"], form.cleaned_data["start_time"])
        else:
            messages.success(request, f"{len(bookings)} booking(s) created")
            return redirect("booking-detail", booking_id=bookings[0].pk)
    return render(request, "booking/booking_form.html", {"form": form, "editing": False})


def _visible_booking(request, booking_id):
    booking = get_object_or_404(Reservation.objects.select_related("room", "organizer", "series").prefetch_related("attendees"), pk=booking_id, kind=Reservation.Kind.BOOKING)
    if not _staff(request) and booking.organizer_id != request.user.pk:
        raise Http404
    return booking


@login_required(login_url="sign-in")
@require_GET
def booking_detail(request, booking_id):
    return render(request, "booking/booking_detail.html", {"booking": _visible_booking(request, booking_id), "staff": _staff(request)})


@login_required(login_url="sign-in")
@require_http_methods(["GET", "POST"])
def booking_edit(request, booking_id):
    booking = _visible_booking(request, booking_id)
    if booking.status != Reservation.Status.CONFIRMED:
        messages.error(request, "Only confirmed bookings can be edited")
        return redirect("booking-detail", booking_id=booking.pk)
    staff = _staff(request)
    local_start, local_end = timezone.localtime(booking.starts_at), timezone.localtime(booking.ends_at)
    initial = {
        "room": booking.room, "date": local_start.date(), "start_time": local_start.time().replace(tzinfo=None),
        "end_time": local_end.time().replace(tzinfo=None), "title": booking.title,
        "description": booking.description, "meeting_type": booking.meeting_type,
        "guest_company_name": booking.guest_company_name, "external_attendee_count": booking.external_attendee_count,
        "department": booking.department, "attendees": "\n".join(booking.attendees.values_list("email", flat=True)),
        "refreshments_requested": booking.refreshments_requested, "front_desk_notes": booking.front_desk_notes,
        "recurrence": "none", "organizer_email": booking.organizer.email,
    }
    form = BookingForm(request.POST or None, initial=initial if request.method == "GET" else None, staff=staff)
    form.fields.pop("recurrence")
    form.fields.pop("until_date")
    if request.method == "POST" and form.is_valid():
        form.cleaned_data["recurrence"] = "none"
        form.cleaned_data["until_date"] = None
        try:
            update_booking(booking.pk, form.cleaned_data, actor=request.user, staff=staff)
        except BookingError as exc:
            form.add_error(None, str(exc))
            if "unavailable" in str(exc).lower():
                queue_conflict_notice(request.user.email, form.cleaned_data["room"].name, form.cleaned_data["date"], form.cleaned_data["start_time"])
        else:
            messages.success(request, "Booking updated")
            return redirect("booking-detail", booking_id=booking.pk)
    return render(request, "booking/booking_form.html", {"form": form, "editing": True, "booking": booking})


@login_required(login_url="sign-in")
@require_POST
def booking_cancel(request, booking_id):
    _visible_booking(request, booking_id)
    try:
        cancel_booking(booking_id, actor=request.user, staff=_staff(request), reason=request.POST.get("reason", "Cancelled") or "Cancelled")
        messages.success(request, "Booking cancelled")
    except BookingError as exc:
        messages.error(request, str(exc))
    return redirect("booking-detail", booking_id=booking_id)


@login_required(login_url="sign-in")
@require_GET
def my_bookings(request):
    bookings = Reservation.objects.filter(kind=Reservation.Kind.BOOKING, organizer=request.user).select_related("room").order_by("-starts_at")[:100]
    return render(request, "booking/my_bookings.html", {"bookings": bookings})


@never_cache
@require_GET
def checkin_link(request, token):
    if len(token) > 128:
        raise Http404
    request.session["pending_checkin_token"] = token
    return redirect("checkin-confirm")


@never_cache
@require_http_methods(["GET", "POST"])
def checkin_confirm(request):
    if request.method == "POST":
        token = request.session.pop("pending_checkin_token", None)
        try:
            booking = confirm_checkin(token, actor=request.user if request.user.is_authenticated else None)
        except CheckInError as exc:
            return render(request, "booking/checkin.html", {"error": str(exc)}, status=400)
        return render(request, "booking/checkin.html", {"success": True, "booking": booking})
    if not request.session.get("pending_checkin_token"):
        return redirect("home")
    return render(request, "booking/checkin.html")
