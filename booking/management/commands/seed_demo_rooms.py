from django.conf import settings
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from booking.models import Room


class Command(BaseCommand):
    help = "Load local demonstration rooms into an empty room directory."

    def handle(self, *args, **options):
        if settings.HTTPS_ENABLED or settings.MAIL_MODE != "file":
            raise CommandError("Demonstration rooms are restricted to local file-email development")
        with transaction.atomic():
            if Room.objects.exists():
                raise CommandError("Rooms already exist; demonstration data will not replace them")
            call_command("loaddata", "demo_rooms", verbosity=0)
        self.stdout.write(self.style.SUCCESS("Five demonstration rooms created"))
