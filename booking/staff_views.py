import io
import re
from datetime import date, datetime, timedelta
from functools import wraps
from zoneinfo import ZoneInfo

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET, require_POST, require_http_methods
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill

from booking.forms import PolicyForm, RoomBlockForm, RoomForm
from booking.models import AuditEvent, BookingPolicy, CompanyHoliday, Notification, Reservation, Room, RoomFacility, User
from booking.services.checkin import CheckInError, manual_checkin
from booking.services.email_login import normalized_employee_email
from booking.services.reservations import ReservationConflict, reserve_time
from booking.services.staff_auth import finish_staff_login, start_staff_login


def staff_required(view):
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        if not request.user.is_authenticated or not request.user.is_active or not request.user.is_staff or request.session.get("staff_verified") is not True:
            return redirect("staff-login")
        return view(request, *args, **kwargs)
    return wrapped


@never_cache
@require_http_methods(["GET", "POST"])
def staff_login(request):
    if request.method == "POST":
        if start_staff_login(request.POST.get("email"), request.POST.get("password"), request):
            return redirect("staff-code")
        messages.error(request, "Sign-in could not be completed. Check your details or contact IT.")
    return render(request, "booking/staff_login.html")


@never_cache
@require_http_methods(["GET", "POST"])
def staff_code(request):
    if not request.session.get("pending_staff_token_id"):
        return redirect("staff-login")
    if request.method == "POST":
        if finish_staff_login(request.POST.get("code", ""), request):
            return redirect("staff-dashboard")
        messages.error(request, "That code is invalid or expired. Request a new code if needed.")
    return render(request, "booking/staff_code.html", {"local_mail": settings.MAIL_MODE == "file" and not settings.HTTPS_ENABLED})


@staff_required
@require_GET
def dashboard(request):
    today = timezone.localdate()
    return render(request, "booking/staff_dashboard.html", {
        "today_bookings": Reservation.objects.filter(kind=Reservation.Kind.BOOKING, starts_at__date=today, status__in=["confirmed", "checked_in", "completed"]).count(),
        "rooms_count": Room.objects.filter(is_active=True).count(),
        "mail_failed": Notification.objects.filter(status=Notification.Status.FAILED).count(),
        "no_shows": Reservation.objects.filter(status=Reservation.Status.NO_SHOW, starts_at__date=today).count(),
        "upcoming": Reservation.objects.filter(kind=Reservation.Kind.BOOKING, starts_at__gte=timezone.now(), status="confirmed").select_related("room", "organizer").order_by("starts_at")[:12],
    })


@staff_required
@require_GET
def rooms(request):
    return render(request, "booking/staff_rooms.html", {"rooms": Room.objects.all().prefetch_related("facilities")})


@staff_required
@require_http_methods(["GET", "POST"])
def room_form(request, room_id=None):
    room = get_object_or_404(Room, pk=room_id) if room_id else None
    form = RoomForm(request.POST or None, instance=room, initial={"facilities_text": "\n".join(room.facilities.values_list("name", flat=True))} if room and request.method == "GET" else None)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            saved = form.save()
            facilities = [item.strip() for item in re.split(r"[\n,;]+", form.cleaned_data["facilities_text"]) if item.strip()]
            RoomFacility.objects.filter(room=saved).delete()
            RoomFacility.objects.bulk_create([RoomFacility(room=saved, name=name) for name in dict.fromkeys(facilities)])
            AuditEvent.objects.create(actor=request.user, action="room_modified" if room else "room_created", target_type="room", target_id=saved.pk, outcome="success", details={"active": saved.is_active})
        messages.success(request, "Room saved")
        return redirect("staff-rooms")
    return render(request, "booking/staff_form.html", {"form": form, "heading": "Edit room" if room else "Add room"})


@staff_required
@require_GET
def bookings(request):
    qs = Reservation.objects.filter(kind=Reservation.Kind.BOOKING).select_related("room", "organizer").order_by("-starts_at")
    search = request.GET.get("q", "").strip()[:100]
    status = request.GET.get("status", "")
    if search:
        qs = qs.filter(Q(title__icontains=search) | Q(organizer__email__icontains=search) | Q(room__name__icontains=search))
    if status in Reservation.Status.values:
        qs = qs.filter(status=status)
    return render(request, "booking/staff_bookings.html", {"bookings": qs[:150], "search": search, "status": status, "statuses": Reservation.Status.choices})


@staff_required
@require_POST
def staff_checkin(request, booking_id):
    try:
        manual_checkin(booking_id, actor=request.user)
        messages.success(request, "Meeting checked in")
    except CheckInError as exc:
        messages.error(request, str(exc))
    return redirect("booking-detail", booking_id=booking_id)


@staff_required
@require_http_methods(["GET", "POST"])
def block_new(request):
    form = RoomBlockForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data
        start = datetime.combine(data["date"], data["start_time"], ZoneInfo("Asia/Kathmandu"))
        end = datetime.combine(data["date"], data["end_time"], ZoneInfo("Asia/Kathmandu"))
        if end <= start:
            form.add_error("end_time", "End must be after start")
        elif start <= timezone.now():
            form.add_error("date", "Choose a future period")
        else:
            try:
                block = reserve_time(
                    room_id=data["room"].pk, occupied_from=start, occupied_until=end,
                    starts_at=start, ends_at=end, kind=Reservation.Kind.BLOCK,
                    status=Reservation.Status.BLOCKED, created_by=request.user,
                    block_reason=data["block_reason"],
                )
            except ReservationConflict:
                form.add_error(None, "This room already has a booking or closure during that time")
            else:
                AuditEvent.objects.create(actor=request.user, action="room_blocked", target_type="reservation", target_id=block.pk, outcome="success")
                messages.success(request, "Room blocked")
                return redirect("staff-blocks")
    return render(request, "booking/staff_form.html", {"form": form, "heading": "Block a room"})


@staff_required
@require_GET
def blocks(request):
    return render(request, "booking/staff_blocks.html", {"blocks": Reservation.objects.filter(kind=Reservation.Kind.BLOCK).select_related("room").order_by("-starts_at")[:100]})


@staff_required
@require_POST
def block_cancel(request, block_id):
    with transaction.atomic():
        block = get_object_or_404(Reservation.objects.select_for_update(), pk=block_id, kind=Reservation.Kind.BLOCK, status=Reservation.Status.BLOCKED)
        block.status = Reservation.Status.BLOCK_CANCELLED
        block.save(update_fields=["status", "updated_at"])
        AuditEvent.objects.create(actor=request.user, action="room_block_cancelled", target_type="reservation", target_id=block.pk, outcome="success")
    messages.success(request, "Room closure removed")
    return redirect("staff-blocks")


@staff_required
@require_http_methods(["GET", "POST"])
def policy(request):
    policy = BookingPolicy.objects.get(pk=1)
    form = PolicyForm(request.POST or None, instance=policy)
    if request.method == "POST" and form.is_valid():
        saved = form.save(commit=False)
        saved.updated_by = request.user
        saved.save()
        AuditEvent.objects.create(actor=request.user, action="policy_modified", target_type="booking_policy", target_id=1, outcome="success")
        messages.success(request, "Booking rules saved")
        return redirect("staff-policy")
    return render(request, "booking/staff_form.html", {"form": form, "heading": "Booking rules"})


@staff_required
@require_http_methods(["GET", "POST"])
def holidays(request):
    if request.method == "POST":
        try:
            day = date.fromisoformat(request.POST.get("date", ""))
            name = request.POST.get("name", "").strip()[:160]
            if not name:
                raise ValueError
            item, created = CompanyHoliday.objects.update_or_create(date=day, defaults={"name": name})
            AuditEvent.objects.create(actor=request.user, action="holiday_saved", target_type="holiday", target_id=item.pk, outcome="success")
            messages.success(request, "Holiday saved")
        except ValueError:
            messages.error(request, "Enter a valid date and holiday name")
        return redirect("staff-holidays")
    return render(request, "booking/staff_holidays.html", {"holidays": CompanyHoliday.objects.all()})


@staff_required
@require_POST
def holiday_delete(request, holiday_id):
    item = get_object_or_404(CompanyHoliday, pk=holiday_id)
    AuditEvent.objects.create(actor=request.user, action="holiday_removed", target_type="holiday", target_id=item.pk, outcome="success")
    item.delete()
    return redirect("staff-holidays")


@staff_required
@require_GET
def users(request):
    return render(request, "booking/staff_users.html", {"users": User.objects.all().order_by("email")[:200]})


@staff_required
@require_POST
def user_save(request):
    email = normalized_employee_email(request.POST.get("email", ""))
    if not email:
        messages.error(request, "Use a valid wdn.com.np email address")
        return redirect("staff-users")
    with transaction.atomic():
        user = User.objects.select_for_update().filter(email__iexact=email).first()
        if user is None:
            user = User.objects.create_user(email)
        active = request.POST.get("is_active") == "on"
        staff = request.POST.get("is_staff") == "on"
        if user.pk == request.user.pk and (not active or not staff):
            messages.error(request, "You cannot remove your own staff access")
            return redirect("staff-users")
        user.is_active, user.is_staff = active, staff
        user.first_name = request.POST.get("first_name", "").strip()[:150]
        user.last_name = request.POST.get("last_name", "").strip()[:150]
        user.department = request.POST.get("department", "").strip()[:120]
        user.save(update_fields=["is_active", "is_staff", "first_name", "last_name", "department"])
        AuditEvent.objects.create(actor=request.user, action="user_access_modified", target_type="user", target_id=user.pk, outcome="success", details={"active": active, "staff": staff})
    messages.success(request, "User saved")
    return redirect("staff-users")


@staff_required
@require_POST
def send_staff_setup(request, user_id):
    user = get_object_or_404(User, pk=user_id, is_staff=True, is_active=True)
    uid = urlsafe_base64_encode(str(user.pk).encode())
    token = default_token_generator.make_token(user)
    link = settings.PUBLIC_BASE_URL.rstrip("/") + f"/staff/set-password/{uid}/{token}/"
    try:
        send_mail("Set your WDN staff password", f"Use this link to set your staff password: {link}\nIf you did not expect this, contact IT.", settings.DEFAULT_FROM_EMAIL, [user.email])
    except Exception:
        messages.error(request, "The setup email could not be sent")
    else:
        AuditEvent.objects.create(actor=request.user, action="staff_setup_sent", target_type="user", target_id=user.pk, outcome="success")
        messages.success(request, "Password setup link sent")
    return redirect("staff-users")


@never_cache
@require_http_methods(["GET", "POST"])
def set_staff_password(request, uid, token):
    try:
        user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_staff=True, is_active=True)
    except (ValueError, TypeError, OverflowError, User.DoesNotExist):
        raise Http404
    if not default_token_generator.check_token(user, token):
        raise Http404
    if request.method == "POST":
        password = request.POST.get("password", "")
        try:
            if password != request.POST.get("confirm", "") or len(password) < 12:
                raise ValidationError("Use matching passwords of at least 12 characters")
            validate_password(password, user)
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages))
        else:
            user.set_password(password)
            user.save(update_fields=["password"])
            AuditEvent.objects.create(actor=user, action="staff_password_set", target_type="user", target_id=user.pk, outcome="success")
            messages.success(request, "Password set. Sign in with your password and email code.")
            return redirect("staff-login")
    return render(request, "booking/staff_password.html")


@staff_required
@require_GET
def audit(request):
    return render(request, "booking/staff_audit.html", {"events": AuditEvent.objects.select_related("actor").order_by("-created_at")[:200]})


def _range(request):
    today = timezone.localdate()
    try:
        start = date.fromisoformat(request.GET.get("from", ""))
    except ValueError:
        start = today.replace(day=1)
    try:
        end = date.fromisoformat(request.GET.get("to", ""))
    except ValueError:
        end = today
    if end < start or (end - start).days > 366:
        raise ValueError("Choose a valid range of up to one year")
    return start, end


def _report_data(start, end):
    records = list(Reservation.objects.filter(kind=Reservation.Kind.BOOKING, starts_at__date__gte=start, starts_at__date__lte=end).select_related("room", "organizer").order_by("starts_at"))
    room_rows = []
    holidays = set(CompanyHoliday.objects.filter(date__gte=start, date__lte=end).values_list("date", flat=True))
    policy = BookingPolicy.objects.get(pk=1)
    weekdays = sum(1 for n in range((end - start).days + 1) if (start + timedelta(days=n)).weekday() < 5 and start + timedelta(days=n) not in holidays)
    available_minutes = weekdays * int((datetime.combine(date.min, policy.closes_at) - datetime.combine(date.min, policy.opens_at)).total_seconds() / 60)
    for room in Room.objects.all().order_by("name"):
        subset = [item for item in records if item.room_id == room.pk]
        occupied_minutes = sum(int((item.ends_at - item.starts_at).total_seconds() / 60) for item in subset if item.status in ("checked_in", "completed"))
        room_rows.append({"room": room, "bookings": len(subset), "completed": sum(x.status == "completed" for x in subset), "cancelled": sum(x.status == "cancelled" for x in subset), "no_shows": sum(x.status == "no_show" for x in subset), "utilization": round(occupied_minutes * 100 / available_minutes, 1) if available_minutes else 0})
    departments = {}
    organizers = {}
    for item in records:
        key = item.department or "Unspecified"
        departments[key] = departments.get(key, 0) + 1
        organizers[item.organizer.email] = organizers.get(item.organizer.email, 0) + 1
    room_rows.sort(key=lambda item: (-item["bookings"], item["room"].name))
    return records, room_rows, sorted(departments.items(), key=lambda item: -item[1]), sorted(organizers.items(), key=lambda item: -item[1])


@staff_required
@require_GET
def reports(request):
    try:
        start, end = _range(request)
    except ValueError as exc:
        messages.error(request, str(exc))
        start, end = timezone.localdate(), timezone.localdate()
    records, room_rows, departments, organizers = _report_data(start, end)
    today = timezone.localdate()
    quarter_start = today.replace(month=((today.month - 1) // 3) * 3 + 1, day=1)
    presets = [
        ("Today", today, today), ("This week", today - timedelta(days=today.weekday()), today),
        ("This month", today.replace(day=1), today), ("This quarter", quarter_start, today),
        ("This year", today.replace(month=1, day=1), today),
    ]
    return render(request, "booking/staff_reports.html", {"start": start, "end": end, "records": records, "room_rows": room_rows, "departments": departments, "organizers": organizers, "presets": presets, "total": len(records)})


@staff_required
@require_GET
def report_excel(request):
    try:
        start, end = _range(request)
    except ValueError:
        raise Http404
    records, room_rows, departments, organizers = _report_data(start, end)
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Bookings"
    sheet.append(["ID", "Date", "Start", "End", "Room", "Organizer", "Department", "Status", "Title"])
    for item in records:
        local_start, local_end = timezone.localtime(item.starts_at), timezone.localtime(item.ends_at)
        sheet.append([item.pk, local_start.date().isoformat(), local_start.strftime("%H:%M"), local_end.strftime("%H:%M"), item.room.name, item.organizer.email, item.department, item.status, item.title])
    room_sheet = workbook.create_sheet("Room usage")
    room_sheet.append(["Room", "Bookings", "Completed", "Cancelled", "No-shows", "Utilization %"])
    for item in room_rows:
        room_sheet.append([item["room"].name, item["bookings"], item["completed"], item["cancelled"], item["no_shows"], item["utilization"]])
    dept_sheet = workbook.create_sheet("Departments")
    dept_sheet.append(["Department", "Bookings"])
    for department, count in departments:
        dept_sheet.append([department, count])
    organizer_sheet = workbook.create_sheet("Organizers")
    organizer_sheet.append(["Organizer", "Bookings"])
    for email, count in organizers:
        organizer_sheet.append([email, count])
    for tab in workbook:
        tab.freeze_panes = "A2"
        tab.auto_filter.ref = tab.dimensions
        for cell in tab[1]:
            cell.font = Font(bold=True, color="FFFFFF")
            cell.fill = PatternFill("solid", fgColor="104068")
        for column in tab.columns:
            letter = column[0].column_letter
            tab.column_dimensions[letter].width = min(50, max(13, max(len(str(cell.value or "")) for cell in column) + 2))
    output = io.BytesIO()
    workbook.save(output)
    response = HttpResponse(output.getvalue(), content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Content-Disposition"] = f'attachment; filename="meeting-room-report-{start}-{end}.xlsx"'
    return response
