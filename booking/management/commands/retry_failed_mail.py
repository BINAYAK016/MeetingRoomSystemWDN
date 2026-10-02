import logging
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from booking.models import AuditEvent, BookingPolicy, Notification, Reservation

logger = logging.getLogger(__name__)


def retry_failed_mail(notification_id=None):
    now = timezone.now()
    check_in_minutes = BookingPolicy.objects.get(pk=1).check_in_minutes
    jobs = Notification.objects.filter(status=Notification.Status.FAILED)
    if notification_id is not None:
        jobs = jobs.filter(pk=notification_id)
    requeued = superseded = 0
    for pk in jobs.values_list("pk", flat=True):
        with transaction.atomic():
            job = (
                Notification.objects.select_for_update(of=("self",))
                .select_related("reservation")
                .filter(pk=pk, status=Notification.Status.FAILED)
                .first()
            )
            if job is None:
                continue
            booking = job.reservation
            eligible = True
            if booking:
                if job.event_type == "reminder":
                    eligible = (
                        booking.status == Reservation.Status.CONFIRMED
                        and now < booking.starts_at + timedelta(minutes=check_in_minutes)
                        and job.body == f"start={booking.starts_at.isoformat()}"
                    )
                elif job.event_type in {"confirmation", "change"}:
                    eligible = (
                        booking.status in {Reservation.Status.CONFIRMED, Reservation.Status.CHECKED_IN}
                        and now < booking.ends_at
                    )
                elif job.event_type == "cancellation":
                    eligible = booking.status == Reservation.Status.CANCELLED
                elif job.event_type == "no_show":
                    eligible = booking.status == Reservation.Status.NO_SHOW
                elif job.event_type == "check_in":
                    eligible = booking.status in {Reservation.Status.CHECKED_IN, Reservation.Status.COMPLETED}
            job.status = Notification.Status.PENDING if eligible else Notification.Status.SKIPPED
            job.attempts = 0 if eligible else job.attempts
            job.last_error = ""
            job.next_attempt_at = now
            job.lease_token = None
            job.lease_expires_at = None
            job.save(
                update_fields=[
                    "status",
                    "attempts",
                    "last_error",
                    "next_attempt_at",
                    "lease_token",
                    "lease_expires_at",
                ]
            )
            AuditEvent.objects.create(
                action="notification_requeued" if eligible else "notification_superseded",
                target_type="notification",
                target_id=job.pk,
                outcome="success",
            )
            requeued += int(eligible)
            superseded += int(not eligible)
    logger.info("Failed mail review completed: requeued=%s superseded=%s", requeued, superseded)
    return requeued, superseded


class Command(BaseCommand):
    help = "Requeue eligible failed booking emails after correcting SMTP; obsolete messages are superseded."

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--all", action="store_true")
        group.add_argument("--id", type=int)

    def handle(self, *args, **options):
        if options.get("id") is not None and options["id"] <= 0:
            raise CommandError("Use a positive notification ID")
        requeued, superseded = retry_failed_mail(options.get("id"))
        self.stdout.write(f"requeued={requeued} superseded={superseded}")
