from django.core.management.base import BaseCommand, CommandError

from booking.health import worker_is_healthy


class Command(BaseCommand):
    help = "Fail unless the booking worker completed a cycle within two minutes."

    def handle(self, *args, **options):
        try:
            healthy = worker_is_healthy()
        except Exception as exc:
            raise CommandError(f"Worker health unavailable ({type(exc).__name__})") from None
        if not healthy:
            raise CommandError("Worker heartbeat is stale or missing")
        self.stdout.write("ok")
