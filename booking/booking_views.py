import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from booking.forms import BookingForm
from booking.models import BookingPolicy, CompanyHoliday, Reservation, Room
from booking.services.auth_security import staff_session_verified
from booking.services.bookings import BookingError, cancel_booking, create_booking, update_booking
from booking.services.checkin import CheckInError, confirm_checkin_hash
from booking.services.notifications import queue_conflict_notice
from booking.ui import paginate


def _staff(request):
    return staff_session_verified(request)


@login_required(login_url="sign-in")
@require_GET
def room_list(request):
    rooms = (
        Room.objects.filter(is_active=True)
        .prefetch_related("facilities")
        .order_by("location", "floor", "name")
    )
    capacity = request.GET.get("capacity", "")[:5]
    search = request.GET.get("q", "").strip()[:100]
    location = request.GET.get("location", "")[:120]
    facility = request.GET.get("facility", "")[:120]
    if capacity.isdigit():
        rooms = rooms.filter(capacity__gte=int(capacity))
    if search:
        rooms = rooms.filter(
            Q(name__icontains=search) | Q(description__icontains=search) | Q(floor__icontains=search)
        )
    if location:
        rooms = rooms.filter(location=location)
    if facility:
        rooms = rooms.filter(facilities__name=facility).distinct()
    context = paginate(request, rooms, 12)
    context.update(
        {
            "rooms": context["page_obj"],
            "capacity": capacity,
            "search": search,
            "location": location,
            "facility": facility,
            "locations": Room.objects.filter(is_active=True)
            .order_by("location")
            .values_list("location", flat=True)
            .distinct(),
            "facilities": Room.objects.filter(is_active=True, facilities__isnull=False)
            .order_by("facilities__name")
            .values_list("facilities__name", flat=True)
            .distinct(),
        }
    )
    return render(request, "booking/rooms.html", context)


@login_required(login_url="sign-in")
@require_GET
def room_detail(request, room_id):
    room = get_object_or_404(Room.objects.prefetch_related("facilities"), pk=room_id, is_active=True)
    return render(request, "booking/room_detail.html", {"room": room})


@login_required(login_url="sign-in")
@require_GET
def calendar_view(request):
    policy = BookingPolicy.objects.get(pk=1)
    local_tz = ZoneInfo("Asia/Kathmandu")
    now = timezone.now()
    today = timezone.localtime(now, local_tz).date()
    staff = _staff(request)
    try:
        selected = datetime.strptime(request.GET.get("date", ""), "%Y-%m-%d").date()
    except ValueError:
        selected = today
    if abs((selected - today).days) > 366:
        selected = today
    view = request.GET.get("view", "day")
    if view not in ("day", "week", "month"):
        view = "day"
    if view == "month" and not staff:
        view = "week"
    rooms = list(Room.objects.filter(is_active=True).order_by("location", "floor", "name"))
    if view == "week":
        first = selected - timedelta(days=selected.weekday())
        days = [first + timedelta(days=i) for i in range(7)]
    elif view == "month":
        first = selected.replace(day=1)
        days = [
            first + timedelta(days=i) for i in range(35) if (first + timedelta(days=i)).month == first.month
        ]
    else:
        days = [selected]
    last = days[-1] + timedelta(days=1)
    holidays = dict(
        CompanyHoliday.objects.filter(date__gte=days[0], date__lt=last).values_list("date", "name")
    )
    bookings = list(
        Reservation.objects.filter(
            room__is_active=True,
            occupied_from__lt=datetime.combine(last, datetime.min.time(), local_tz),
            occupied_until__gt=datetime.combine(days[0], datetime.min.time(), local_tz),
            status__in=[
                Reservation.Status.CONFIRMED,
                Reservation.Status.CHECKED_IN,
                Reservation.Status.COMPLETED,
                Reservation.Status.BLOCKED,
            ],
        ).select_related("room")
    )
    by_room = {room.pk: [] for room in rooms}
    daily_counts = {}
    for item in bookings:
        by_room[item.room_id].append(item)
        key = (item.room_id, timezone.localtime(item.starts_at, local_tz).date())
        daily_counts[key] = daily_counts.get(key, 0) + 1

    def closed_reason(day):
        if day.weekday() >= 5:
            return "Office closed for the weekend"
        if day in holidays:
            return f"Company holiday: {holidays[day]}"
        if day < today:
            return "Past date"
        if day > today + timedelta(days=policy.advance_days):
            return f"Outside the {policy.advance_days}-day booking window"
        return ""

    if view == "day":
        slots = []
        cursor = datetime.combine(selected, policy.opens_at, local_tz)
        end = datetime.combine(selected, policy.closes_at, local_tz)
        date_reason = closed_reason(selected)
        while cursor < end:
            slot_end = cursor + timedelta(minutes=policy.slot_minutes)
            cells = []
            for room in rooms:
                occupying = next(
                    (
                        item
                        for item in by_room[room.pk]
                        if item.occupied_from < slot_end and item.occupied_until > cursor
                    ),
                    None,
                )
                own = bool(occupying and occupying.organizer_id == request.user.pk)
                reason = date_reason
                if not reason and cursor <= now:
                    reason = "Start time has passed"
                if not reason and cursor + timedelta(minutes=policy.minimum_minutes) > end:
                    reason = "Not enough time before closing"
                cells.append(
                    {
                        "room": room,
                        "occupied": occupying,
                        "own": own,
                        "can_open": bool(
                            occupying and occupying.kind == Reservation.Kind.BOOKING and (own or staff)
                        ),
                        "unavailable_reason": reason,
                        "available": occupying is None and not reason,
                    }
                )
            slots.append({"time": cursor, "cells": cells})
            cursor = slot_end
        return render(
            request,
            "booking/calendar.html",
            {
                "view": view,
                "selected": selected,
                "rooms": rooms,
                "slots": slots,
                "policy": policy,
                "staff": staff,
                "date_unavailable_reason": date_reason,
            },
        )
    day_rows = []
    for day in days:
        day_rows.append(
            {
                "date": day,
                "unavailable_reason": closed_reason(day),
                "cells": [{"room": room, "count": daily_counts.get((room.pk, day), 0)} for room in rooms],
            }
        )
    return render(
        request,
        "booking/calendar.html",
        {
            "view": view,
            "selected": selected,
            "rooms": rooms,
            "day_rows": day_rows,
            "policy": policy,
            "staff": staff,
        },
    )


@login_required(login_url="sign-in")
@require_http_methods(["GET", "POST"])
def booking_new(request):
    staff = _staff(request)
    initial = {
        "room": request.GET.get("room"),
        "date": request.GET.get("date"),
        "start_time": request.GET.get("start"),
        "meeting_type": "internal",
        "recurrence": "none",
        "department": request.user.department,
    }
    form = BookingForm(
        request.POST or None, initial=initial if request.method == "GET" else None, staff=staff
    )
    if request.method == "POST" and form.is_valid():
        try:
            bookings = create_booking(form.cleaned_data, actor=request.user, staff=staff)
        except BookingError as exc:
            form.add_error(None, str(exc))
            if "unavailable" in str(exc).lower():
                queue_conflict_notice(
                    request.user.email,
                    form.cleaned_data["room"].name,
                    form.cleaned_data["date"],
                    form.cleaned_data["start_time"],
                )
        else:
            messages.success(request, f"{len(bookings)} booking(s) created")
            return redirect("booking-detail", booking_id=bookings[0].pk)
    return render(request, "booking/booking_form.html", {"form": form, "editing": False})


def _visible_booking(request, booking_id):
    booking = get_object_or_404(
        Reservation.objects.select_related("room", "organizer", "series").prefetch_related("attendees"),
        pk=booking_id,
        kind=Reservation.Kind.BOOKING,
    )
    if not _staff(request) and booking.organizer_id != request.user.pk:
        raise Http404
    return booking


@login_required(login_url="sign-in")
@require_GET
def booking_detail(request, booking_id):
    return render(
        request,
        "booking/booking_detail.html",
        {"booking": _visible_booking(request, booking_id), "staff": _staff(request)},
    )


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
        "room": booking.room,
        "date": local_start.date(),
        "start_time": local_start.time().replace(tzinfo=None),
        "end_time": local_end.time().replace(tzinfo=None),
        "title": booking.title,
        "description": booking.description,
        "meeting_type": booking.meeting_type,
        "guest_company_name": booking.guest_company_name,
        "external_attendee_count": booking.external_attendee_count,
        "department": booking.department,
        "attendees": "\n".join(booking.attendees.values_list("email", flat=True)),
        "refreshments_requested": booking.refreshments_requested,
        "front_desk_notes": booking.front_desk_notes,
        "recurrence": "none",
        "organizer_email": booking.organizer.email,
    }
    form = BookingForm(
        request.POST or None, initial=initial if request.method == "GET" else None, staff=staff
    )
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
                queue_conflict_notice(
                    request.user.email,
                    form.cleaned_data["room"].name,
                    form.cleaned_data["date"],
                    form.cleaned_data["start_time"],
                )
        else:
            messages.success(request, "Booking updated")
            return redirect("booking-detail", booking_id=booking.pk)
    return render(request, "booking/booking_form.html", {"form": form, "editing": True, "booking": booking})


@login_required(login_url="sign-in")
@require_POST
def booking_cancel(request, booking_id):
    _visible_booking(request, booking_id)
    try:
        cancel_booking(
            booking_id,
            actor=request.user,
            staff=_staff(request),
            reason=request.POST.get("reason", "Cancelled") or "Cancelled",
        )
        messages.success(request, "Booking cancelled")
    except BookingError as exc:
        messages.error(request, str(exc))
    return redirect("booking-detail", booking_id=booking_id)


@login_required(login_url="sign-in")
@require_GET
def my_bookings(request):
    bookings = Reservation.objects.filter(
        kind=Reservation.Kind.BOOKING, organizer=request.user
    ).select_related("room")
    period = request.GET.get("period", "upcoming")
    if period == "upcoming":
        bookings = bookings.filter(
            ends_at__gte=timezone.now(), status__in=["confirmed", "checked_in"]
        ).order_by("starts_at", "pk")
    else:
        period = "history"
        bookings = bookings.order_by("-starts_at", "-pk")
    context = paginate(request, bookings)
    context.update({"bookings": context["page_obj"], "period": period})
    return render(request, "booking/my_bookings.html", context)


@never_cache
@require_GET
def checkin_link(request, token):
    if len(token) > 128:
        raise Http404
    request.session["pending_checkin_token"] = hashlib.sha256(token.encode()).hexdigest()
    return redirect("checkin-confirm")


@never_cache
@require_http_methods(["GET", "POST"])
def checkin_confirm(request):
    context = {"check_in_minutes": BookingPolicy.objects.get(pk=1).check_in_minutes}
    if request.method == "POST":
        token = request.session.get("pending_checkin_token")
        try:
            booking = confirm_checkin_hash(
                token, actor=request.user if request.user.is_authenticated else None
            )
        except CheckInError as exc:
            context.update({"error": str(exc), "can_retry": bool(token)})
            return render(request, "booking/checkin.html", context, status=400)
        request.session.pop("pending_checkin_token", None)
        return render(request, "booking/checkin.html", {"success": True, "booking": booking})
    if not request.session.get("pending_checkin_token"):
        return redirect("home")
    return render(request, "booking/checkin.html", context)
