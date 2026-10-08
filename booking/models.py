from datetime import time

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateTimeRangeField, RangeBoundary, RangeOperators
from django.db import models
from django.db.models import F, Func, Q
from django.db.models.functions import Lower
from django.utils.crypto import salted_hmac

ACTIVE_RESERVATION_STATUSES = ("pending", "approved", "checked_in", "completed", "blocked")


class UserManager(BaseUserManager):
    use_in_migrations = True

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("An email address is required")
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields["is_staff"] is not True or extra_fields["is_superuser"] is not True:
            raise ValueError("A superuser must have staff and superuser access")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    username = None
    email = models.EmailField(unique=True)
    department = models.CharField(max_length=120, blank=True)
    auth_version = models.PositiveIntegerField(default=1)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []
    objects = UserManager()

    def _get_session_auth_hash(self, secret=None):
        return salted_hmac(
            "booking.User.get_session_auth_hash",
            f"{self.password}:{self.auth_version}",
            secret=secret,
            algorithm="sha256",
        ).hexdigest()

    class Meta:
        db_table = "users"
        constraints = [
            models.UniqueConstraint(Lower("email"), name="users_email_ci_unique"),
        ]

    def __str__(self):
        return self.email


class Room(models.Model):
    name = models.CharField(max_length=120)
    location = models.CharField(max_length=120)
    floor = models.CharField(max_length=40)
    capacity = models.PositiveSmallIntegerField()
    description = models.TextField(blank=True)
    instructions = models.TextField(blank=True)
    photo = models.ImageField(upload_to="rooms/photos/", blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "rooms"
        ordering = ["location", "floor", "name"]
        constraints = [
            models.UniqueConstraint(
                fields=["location", "floor", "name"], name="room_location_floor_name_unique"
            ),
            models.CheckConstraint(condition=Q(capacity__gt=0), name="room_capacity_positive"),
        ]

    def __str__(self):
        return f"{self.name} ({self.location}, {self.floor})"


class RoomFacility(models.Model):
    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="facilities")
    name = models.CharField(max_length=120)

    class Meta:
        db_table = "room_facilities"
        constraints = [
            models.UniqueConstraint(fields=["room", "name"], name="room_facility_unique"),
        ]


class BookingSeries(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "daily", "Daily"
        WEEKLY = "weekly", "Weekly"
        MONTHLY = "monthly", "Monthly"

    room = models.ForeignKey(Room, on_delete=models.PROTECT)
    organizer = models.ForeignKey(User, on_delete=models.PROTECT, related_name="organized_series")
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_series")
    frequency = models.CharField(max_length=10, choices=Frequency.choices)
    first_date = models.DateField()
    last_date = models.DateField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "booking_series"
        constraints = [
            models.CheckConstraint(condition=Q(first_date__lte=F("last_date")), name="series_dates_ordered"),
        ]


class TsTzRange(Func):
    function = "TSTZRANGE"
    output_field = DateTimeRangeField()


class Reservation(models.Model):
    class Kind(models.TextChoices):
        BOOKING = "booking", "Booking"
        BLOCK = "block", "Room closure"

    class Status(models.TextChoices):
        PENDING = "pending", "Pending approval"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"
        CHECKED_IN = "checked_in", "Checked in"
        COMPLETED = "completed", "Completed"
        CANCELLED = "cancelled", "Cancelled"
        NO_SHOW = "no_show", "No show"
        BLOCKED = "blocked", "Blocked"
        BLOCK_CANCELLED = "block_cancelled", "Closure cancelled"

    class MeetingType(models.TextChoices):
        INTERNAL = "internal", "Internal"
        EXTERNAL = "external", "External"
        MIXED = "mixed", "Internal + External"

    room = models.ForeignKey(Room, on_delete=models.PROTECT, related_name="reservations")
    series = models.ForeignKey(
        BookingSeries, null=True, blank=True, on_delete=models.PROTECT, related_name="occurrences"
    )
    organizer = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="organized_reservations"
    )
    created_by = models.ForeignKey(User, on_delete=models.PROTECT, related_name="created_reservations")
    kind = models.CharField(max_length=7, choices=Kind.choices)
    status = models.CharField(max_length=16, choices=Status.choices)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    occupied_from = models.DateTimeField()
    occupied_until = models.DateTimeField()
    title = models.CharField(max_length=200, blank=True)
    description = models.TextField(blank=True)
    meeting_type = models.CharField(max_length=8, choices=MeetingType.choices, default=MeetingType.INTERNAL)
    guest_company_name = models.CharField(max_length=200, blank=True)
    external_attendee_count = models.PositiveSmallIntegerField(default=0)
    department = models.CharField(max_length=120, blank=True)
    refreshments_requested = models.BooleanField(default=False)
    front_desk_notes = models.TextField(blank=True)
    block_reason = models.CharField(max_length=240, blank=True)
    override_reason = models.TextField(blank=True)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=240, blank=True)
    approved_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="approved_reservations"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.PROTECT, related_name="rejected_reservations"
    )
    rejected_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.CharField(max_length=500, blank=True)
    revision = models.PositiveIntegerField(default=1)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "reservations"
        indexes = [
            models.Index(fields=["room", "starts_at"], name="reservations_room_start_idx"),
            models.Index(fields=["organizer", "starts_at"], name="reservations_org_start_idx"),
            models.Index(fields=["status", "starts_at"], name="reservations_status_start_idx"),
            models.Index(
                fields=["created_at"], condition=Q(status="pending"), name="reservations_pending_idx"
            ),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(starts_at__lt=F("ends_at")), name="reservation_time_ordered"),
            models.CheckConstraint(
                condition=Q(occupied_from__lte=F("starts_at"), occupied_until__gte=F("ends_at")),
                name="reservation_occupied_contains_time",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="booking", organizer__isnull=False)
                    & ~Q(title="")
                    & Q(
                        status__in=[
                            "pending",
                            "approved",
                            "rejected",
                            "checked_in",
                            "completed",
                            "cancelled",
                            "no_show",
                        ]
                    )
                )
                | (
                    Q(kind="block", organizer__isnull=True)
                    & ~Q(block_reason="")
                    & Q(status__in=["blocked", "block_cancelled"])
                ),
                name="reservation_kind_status_fields_valid",
            ),
            models.CheckConstraint(
                condition=~Q(status="rejected") | (~Q(rejection_reason="") & Q(rejected_at__isnull=False)),
                name="reservation_rejection_has_reason",
            ),
            models.CheckConstraint(
                condition=Q(kind="block")
                | Q(meeting_type="internal")
                | (Q(meeting_type__in=["external", "mixed"]) & ~Q(guest_company_name="")),
                name="external_meeting_has_company",
            ),
            ExclusionConstraint(
                name="reservation_room_occupied_no_overlap",
                expressions=[
                    (
                        TsTzRange("occupied_from", "occupied_until", RangeBoundary()),
                        RangeOperators.OVERLAPS,
                    ),
                    ("room", RangeOperators.EQUAL),
                ],
                condition=Q(status__in=ACTIVE_RESERVATION_STATUSES),
            ),
        ]

    def __str__(self):
        return self.title if self.kind == self.Kind.BOOKING else f"Closure: {self.block_reason}"


class BookingAttendee(models.Model):
    reservation = models.ForeignKey(Reservation, on_delete=models.PROTECT, related_name="attendees")
    email = models.EmailField()
    name = models.CharField(max_length=160, blank=True)

    class Meta:
        db_table = "booking_attendees"
        constraints = [
            models.UniqueConstraint(fields=["reservation", "email"], name="reservation_attendee_unique"),
        ]


class EmailToken(models.Model):
    class Purpose(models.TextChoices):
        LOGIN = "login", "Login"
        CHECK_IN = "check_in", "Check-in"
        STAFF = "staff", "Staff sign-in code"

    user = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    reservation = models.ForeignKey(Reservation, null=True, blank=True, on_delete=models.PROTECT)
    email = models.EmailField()
    purpose = models.CharField(max_length=10, choices=Purpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "email_tokens"
        indexes = [
            models.Index(fields=["purpose", "expires_at"], name="email_token_expiry_idx"),
            models.Index(fields=["purpose", "email", "-created_at"], name="email_token_request_idx"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(purpose__in=["login", "staff"], reservation__isnull=True)
                | Q(purpose="check_in", reservation__isnull=False),
                name="email_token_purpose_target_valid",
            ),
        ]


class AuthenticationThrottle(models.Model):
    purpose = models.CharField(max_length=40)
    key = models.CharField(max_length=64)
    window_started_at = models.DateTimeField()
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "authentication_throttles"
        constraints = [
            models.UniqueConstraint(fields=["purpose", "key"], name="auth_throttle_purpose_key_unique"),
        ]
        indexes = [models.Index(fields=["window_started_at"], name="auth_throttle_window_idx")]


class Notification(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        SENDING = "sending", "Sending"
        SENT = "sent", "Sent"
        FAILED = "failed", "Failed"
        SKIPPED = "skipped", "Superseded"

    reservation = models.ForeignKey(Reservation, null=True, blank=True, on_delete=models.PROTECT)
    reservation_revision = models.PositiveIntegerField(null=True, blank=True)
    recipient_email = models.EmailField()
    event_type = models.CharField(max_length=40)
    subject = models.CharField(max_length=240)
    body = models.TextField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    next_attempt_at = models.DateTimeField()
    sent_at = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=240, blank=True)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "notifications"
        indexes = [models.Index(fields=["status", "next_attempt_at"], name="notification_due_idx")]


class AuditEvent(models.Model):
    actor = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    action = models.CharField(max_length=80)
    target_type = models.CharField(max_length=60, blank=True)
    target_id = models.BigIntegerField(null=True, blank=True)
    outcome = models.CharField(max_length=20)
    details = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "audit_events"
        indexes = [
            models.Index(fields=["-created_at"], name="audit_recent_idx"),
            models.Index(fields=["actor", "-created_at"], name="audit_actor_recent_idx"),
        ]


class BookingPolicy(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    opens_at = models.TimeField(default=time(9, 0))
    closes_at = models.TimeField(default=time(17, 0))
    minimum_minutes = models.PositiveSmallIntegerField(default=30)
    maximum_minutes = models.PositiveSmallIntegerField(default=120)
    slot_minutes = models.PositiveSmallIntegerField(default=15)
    gap_minutes = models.PositiveSmallIntegerField(default=15)
    advance_days = models.PositiveSmallIntegerField(default=14)
    check_in_minutes = models.PositiveSmallIntegerField(default=15)
    updated_by = models.ForeignKey(User, null=True, blank=True, on_delete=models.PROTECT)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "booking_policy"
        constraints = [
            models.CheckConstraint(condition=Q(id=1), name="booking_policy_singleton"),
            models.CheckConstraint(
                condition=Q(opens_at__lt=F("closes_at")), name="booking_policy_hours_ordered"
            ),
            models.CheckConstraint(
                condition=Q(minimum_minutes__lte=F("maximum_minutes")), name="booking_policy_duration_ordered"
            ),
            models.CheckConstraint(
                condition=Q(slot_minutes__gt=0, advance_days__gt=0), name="booking_policy_steps_positive"
            ),
            models.CheckConstraint(
                condition=Q(
                    minimum_minutes__gt=0,
                    maximum_minutes__lte=1440,
                    slot_minutes__lte=60,
                    gap_minutes__lte=120,
                    advance_days__lte=366,
                    check_in_minutes__gt=0,
                    check_in_minutes__lte=F("minimum_minutes"),
                ),
                name="booking_policy_valid_limits",
            ),
        ]


class CompanyHoliday(models.Model):
    date = models.DateField(unique=True)
    name = models.CharField(max_length=160)

    class Meta:
        db_table = "company_holidays"
        ordering = ["date"]


class WorkerHeartbeat(models.Model):
    id = models.PositiveSmallIntegerField(primary_key=True, default=1, editable=False)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_error_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "worker_heartbeat"
        constraints = [models.CheckConstraint(condition=Q(id=1), name="worker_heartbeat_singleton")]
