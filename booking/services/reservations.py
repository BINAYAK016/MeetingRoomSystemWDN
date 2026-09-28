from django.db import IntegrityError, transaction

from booking.models import ACTIVE_RESERVATION_STATUSES, Reservation, Room


class ReservationConflict(Exception):
    """The requested room time is already occupied."""


class RoomUnavailable(Exception):
    """The room is inactive or cannot be reserved."""


def reserve_time(*, room_id, occupied_from, occupied_until, kind, **details):
    """Save a prepared reservation while serializing writes for one room.

    Policy, identity, and field validation belong to the higher-level booking
    workflow. This low-level function is the shared write path for meetings and
    room closures; the database constraint remains the final conflict guard.
    """
    try:
        with transaction.atomic():
            room = Room.objects.select_for_update().get(pk=room_id)
            if kind == Reservation.Kind.BOOKING and not room.is_active:
                raise RoomUnavailable("This room is not available for booking")

            conflict = Reservation.objects.filter(
                room=room,
                status__in=ACTIVE_RESERVATION_STATUSES,
                occupied_from__lt=occupied_until,
                occupied_until__gt=occupied_from,
            ).exists()
            if conflict:
                raise ReservationConflict("This room is unavailable for the selected time")

            return Reservation.objects.create(
                room=room,
                occupied_from=occupied_from,
                occupied_until=occupied_until,
                kind=kind,
                **details,
            )
    except IntegrityError as exc:
        if getattr(exc.__cause__, "sqlstate", None) == "23P01":
            raise ReservationConflict("This room is unavailable for the selected time") from exc
        raise
