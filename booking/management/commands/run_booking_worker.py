import logging
import time

from django.core.management.base import BaseCommand
from django.db import close_old_connections

from booking.services.checkin import complete_finished, release_due_no_shows
from booking.services.notifications import queue_due_reminders, send_due_notifications


logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Send queued email, schedule reminders, and release missed check-ins."

    def add_arguments(self, parser):
        parser.add_argument("--once", action="store_true")

    def handle(self, *args, **options):
        while True:
            close_old_connections()
            try:
                released = release_due_no_shows()
                completed = complete_finished()
                reminded = queue_due_reminders()
                sent = send_due_notifications()
                if released or completed or reminded or sent:
                    self.stdout.write(f"released={released} completed={completed} reminders={reminded} sent={sent}")
            except Exception:
                logger.exception("Booking worker cycle failed")
                if options["once"]:
                    raise
            finally:
                close_old_connections()
            if options["once"]:
                break
            time.sleep(30)
