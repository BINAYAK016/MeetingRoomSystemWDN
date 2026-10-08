import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from booking.forms import BookingForm, BookingScheduleForm
from booking.models import ACTIVE_RESERVATION_STATUSES, BookingPolicy, CompanyHoliday, Reservation, Room
from booking.services.auth_security import staff_session_verified
from booking.services.bookings import (
    BookingError,
    cancel_booking,
    create_booking,
    prepared_booking_intervals,
    update_booking,
)
from booking.services.checkin import CheckInError, confirm_checkin_hash
from booking.services.notifications import queue_conflict_notice
from booking.ui import paginate


def _staff(request):
    return staff_session_verified(request)


def _booking_form_context(request, *, booking=None):
    policy = BookingPolicy.objects.get(pk=1)
    local_now = timezone.localtime(timezone.now(), ZoneInfo("Asia/Kathmandu"))
    today = local_now.date()
    availability_url = reverse("booking-availability")
    return {
        "availability_url": availability_url,
        "booking_ui": {
            "availability_url": availability_url,
            "today": today.isoformat(),
            "latest_date": (today + timedelta(days=policy.advance_days)).isoformat(),
            "opens_at": policy.opens_at.strftime("%H:%M"),
            "closes_at": policy.closes_at.strftime("%H:%M"),
            "minimum_minutes": policy.minimum_minutes,
            "maximum_minutes": policy.maximum_minutes,
            "slot_minutes": policy.slot_minutes,
            "check_in_minutes": policy.check_in_minutes,
            "advance_days": policy.advance_days,
            "local_now": local_now.isoformat(),
            "staff": _staff(request),
            "booking_id": booking.pk if booking else None,
            "actor_email": request.user.email,
        },
        "booking_rooms": Room.objects.filter(is_active=True)
        .prefetch_related("facilities")
        .order_by("location", "floor", "name"),
    }


def _new_booking_initial(request):
    policy = BookingPolicy.objects.get(pk=1)
    now = timezone.localtime(timezone.now(), ZoneInfo("Asia/Kathmandu"))
    today = now.date()
    step = policy.slot_minutes
    opens = policy.opens_at.hour * 60 + policy.opens_at.minute
    closes = policy.closes_at.hour * 60 + policy.closes_at.minute
    duration = min(
        policy.maximum_minutes, closes - opens, max(policy.minimum_minutes, ((60 + step - 1) // step) * step)
    )
    next_slot = ((now.hour * 60 + now.minute) // step + 1) * step
    requested_date = request.GET.get("date", "")
    try:
        selected = datetime.strptime(requested_date, "%Y-%m-%d").date()
    except ValueError:
        selected = today
    default_start = max(opens, next_slot) if selected == today else opens
    if not requested_date:
        holidays = set(
            CompanyHoliday.objects.filter(
                date__gte=today, date__lte=today + timedelta(days=policy.advance_days)
            ).values_list("date", flat=True)
        )
        while selected < today + timedelta(days=policy.advance_days) and (
            selected.weekday() >= 5 or selected in holidays or default_start + duration > closes
        ):
            selected += timedelta(days=1)
            default_start = opens
    start = request.GET.get("start") or f"{default_start // 60:02}:{default_start % 60:02}"
    try:
        start_clock = datetime.strptime(start, "%H:%M").time()
        end_minutes = start_clock.hour * 60 + start_clock.minute + duration
        end = f"{end_minutes // 60:02}:{end_minutes % 60:02}" if end_minutes < 1440 else ""
    except ValueError:
        end = ""
    return {
        "room": request.GET.get("room"),
        "date": requested_date or selected.isoformat(),
        "start_time": start,
        "end_time": end,
        "meeting_type": "internal",
        "recurrence": "none",
        "department": request.user.department,
    }


@never_cache
@require_GET
def booking_availability(request):
    if not request.user.is_authenticated or not request.user.is_active:
        return JsonResponse({"ok": False, "error": "Sign in to check room availability."}, status=401)
    staff = _staff(request)
    booking_id = request.GET.get("booking_id", "")
    excluded_id = None
    if booking_id:
        if (
            not booking_id.isascii()
            or not booking_id.isdigit()
            or len(booking_id) > 19
            or int(booking_id) > 9223372036854775807
        ):
            return JsonResponse({"ok": False, "error": "Choose a valid booking to edit."}, status=400)
        try:
            editing = _visible_booking(request, int(booking_id))
        except Http404:
            return JsonResponse({"ok": False, "error": "This booking is unavailable."}, status=404)
        if (
            editing.status not in [Reservation.Status.PENDING, Reservation.Status.APPROVED]
            or editing.starts_at <= timezone.now()
        ):
            return JsonResponse(
                {"ok": False, "error": "Only upcoming pending or approved bookings can be edited."},
                status=400,
            )
        excluded_id = editing.pk
    query = request.GET.copy()
    if excluded_id:
        # The edit workflow changes one occurrence; submitted recurrence fields are ignored there too.
        query["recurrence"] = "none"
        query["until_date"] = ""
    form = BookingScheduleForm(query, staff=staff)
    if not form.is_valid():
        errors = {field: list(messages) for field, messages in form.errors.items()}
        field = next(iter(errors))
        label = form.fields[field].label or field.replace("_", " ").capitalize()
        return JsonResponse(
            {"ok": False, "error": f"{label}: {errors[field][0]}", "fields": errors}, status=400
        )
    policy = BookingPolicy.objects.get(pk=1)
    try:
        intervals = prepared_booking_intervals(form.cleaned_data, policy, staff=staff)
    except BookingError as exc:
        return JsonResponse({"ok": False, "error": str(exc)}, status=400)
    rooms = list(
        Room.objects.filter(is_active=True)
        .prefetch_related("facilities")
        .order_by("location", "floor", "name")
    )
    reservations = Reservation.objects.filter(
        room_id__in=[room.pk for room in rooms],
        status__in=ACTIVE_RESERVATION_STATUSES,
        occupied_from__lt=max(item[3] for item in intervals),
        occupied_until__gt=min(item[2] for item in intervals),
    )
    if excluded_id:
        reservations = reservations.exclude(pk=excluded_id)
    occupied_by_room = {room.pk: [] for room in rooms}
    for room_id, occupied_from, occupied_until in reservations.values_list(
        "room_id", "occupied_from", "occupied_until"
    ):
        occupied_by_room[room_id].append((occupied_from, occupied_until))
    local_tz = ZoneInfo("Asia/Kathmandu")
    room_data = []
    for room in rooms:
        conflicts = []
        for start, _end, occupied_from, occupied_until in intervals:
            for busy_from, busy_until in occupied_by_room[room.pk]:
                if busy_from < occupied_until and busy_until > occupied_from:
                    conflicts.append(
                        {
                            "date": start.date().isoformat(),
                            "occupied_from": timezone.localtime(busy_from, local_tz).isoformat(),
                            "occupied_until": timezone.localtime(busy_until, local_tz).isoformat(),
                        }
                    )
        room_data.append(
            {
                "id": room.pk,
                "name": room.name,
                "location": room.location,
                "floor": room.floor,
                "capacity": room.capacity,
                "description": room.description,
                "instructions": room.instructions,
                "facilities": [facility.name for facility in room.facilities.all()],
                "photo_url": reverse("room-photo", args=[room.pk]) if getattr(room, "photo", None) else "",
                "available": not conflicts,
                "conflicts": conflicts,
            }
        )
    return JsonResponse(
        {
            "ok": True,
            "timezone": "Asia/Kathmandu",
            "occurrences": [
                {
                    "date": item[0].date().isoformat(),
                    "starts_at": item[0].isoformat(),
                    "ends_at": item[1].isoformat(),
                }
                for item in intervals
            ],
            "rooms": room_data,
        }
    )


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
    if capacity.isascii() and capacity.isdigit():
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
            room_id__in=[room.pk for room in rooms],
            occupied_from__lt=datetime.combine(last, datetime.min.time(), local_tz),
            occupied_until__gt=datetime.combine(days[0], datetime.min.time(), local_tz),
            status__in=ACTIVE_RESERVATION_STATUSES,
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
                if not reason and not occupying:
                    minimum_end = cursor + timedelta(minutes=policy.minimum_minutes + policy.gap_minutes)
                    if any(
                        item.occupied_from < minimum_end and item.occupied_until > cursor
                        for item in by_room[room.pk]
                    ):
                        reason = "Not enough time for a meeting and buffer"
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
    initial = _new_booking_initial(request) if request.method == "GET" else None
    form = BookingForm(
        request.POST if request.method == "POST" else None,
        initial=initial if request.method == "GET" else None,
        staff=staff,
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
            if staff:
                messages.success(request, f"{len(bookings)} approved booking(s) created.")
            else:
                messages.success(request, "Booking request submitted. Waiting for administrator approval.")
            return redirect("booking-detail", booking_id=bookings[0].pk)
    context = _booking_form_context(request)
    context.update({"form": form, "editing": False, "staff": staff})
    return render(request, "booking/booking_form.html", context)


def _visible_booking(request, booking_id):
    booking = get_object_or_404(
        Reservation.objects.select_related(
            "room", "organizer", "series", "approved_by", "rejected_by"
        ).prefetch_related("attendees"),
        pk=booking_id,
        kind=Reservation.Kind.BOOKING,
    )
    if not _staff(request) and booking.organizer_id != request.user.pk:
        raise Http404
    return booking


@login_required(login_url="sign-in")
@require_GET
def booking_detail(request, booking_id):
    booking = _visible_booking(request, booking_id)
    staff = _staff(request)
    upcoming = booking.starts_at > timezone.now()
    return render(
        request,
        "booking/booking_detail.html",
        {
            "booking": booking,
            "staff": staff,
            "can_edit": upcoming
            and booking.status in [Reservation.Status.PENDING, Reservation.Status.APPROVED],
            "can_cancel": booking.status
            in [Reservation.Status.PENDING, Reservation.Status.APPROVED, Reservation.Status.CHECKED_IN],
            "can_review": staff and upcoming and booking.status == Reservation.Status.PENDING,
        },
    )


@login_required(login_url="sign-in")
@require_http_methods(["GET", "POST"])
def booking_edit(request, booking_id):
    booking = _visible_booking(request, booking_id)
    if (
        booking.status not in [Reservation.Status.PENDING, Reservation.Status.APPROVED]
        or booking.starts_at <= timezone.now()
    ):
        messages.error(request, "Only upcoming pending or approved bookings can be edited")
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
        "override_reason": booking.override_reason,
    }
    form = BookingForm(
        request.POST if request.method == "POST" else None,
        initial=initial if request.method == "GET" else None,
        staff=staff,
    )
    form.fields.pop("recurrence")
    form.fields.pop("until_date")
    if request.method == "POST" and form.is_valid():
        form.cleaned_data["recurrence"] = "none"
        form.cleaned_data["until_date"] = None
        try:
            updated = update_booking(booking.pk, form.cleaned_data, actor=request.user, staff=staff)
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
            if updated.status == Reservation.Status.PENDING:
                messages.success(request, "Booking request updated. Waiting for administrator approval.")
            else:
                messages.success(request, "Booking updated")
            return redirect("booking-detail", booking_id=booking.pk)
    context = _booking_form_context(request, booking=booking)
    context.update({"form": form, "editing": True, "booking": booking, "staff": staff})
    return render(request, "booking/booking_form.html", context)


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
            ends_at__gte=timezone.now(), status__in=["pending", "approved", "checked_in"]
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
