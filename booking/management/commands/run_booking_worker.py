import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections
from django.utils import timezone

from booking.models import WorkerHeartbeat
from booking.services.checkin import complete_finished, release_due_no_shows
from booking.services.notifications import queue_due_reminders, send_due_notifications

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send queued email, schedule reminders, and release missed check-ins."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        next_reconciliation = 0
        while True:
            cycle_started = time.monotonic()
            close_old_connections()
            try:
                released = completed = reminded = 0
                if cycle_started >= next_reconciliation:
                    released = release_due_no_shows()
                    completed = complete_finished()
                    reminded = queue_due_reminders()
                    WorkerHeartbeat.objects.update_or_create(
                        pk=1, defaults={"last_success_at": timezone.now()}
                    )
                    next_reconciliation = time.monotonic() + 30
                # One bounded SMTP send keeps reconciliation within the next cycle.
                sent = send_due_notifications(limit=1)
                if released or completed or reminded or sent:
                    self.stdout.write(
                        f"released={released} completed={completed} reminders={reminded} sent={sent}"
                    )
            except Exception as exc:
                logger.error("Booking worker cycle failed (%s)", type(exc).__name__)
                try:
                    WorkerHeartbeat.objects.update_or_create(pk=1, defaults={"last_error_at": timezone.now()})
                except Exception:
                    pass
                if options["once"]:
                    raise
            finally:
                close_old_connections()
            if options["once"]:
                break
            time.sleep(max(0, 1 - (time.monotonic() - cycle_started)))
