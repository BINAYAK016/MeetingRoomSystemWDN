"""Read access follows the current organizer and attendee list of each occurrence."""

from django.db.models import BooleanField, Case, Exists, OuterRef, Q, Value, When

from booking.models import BookingAttendee, Reservation


def with_meeting_membership(queryset, user):
    email = user.email.strip().lower()
    attending = BookingAttendee.objects.filter(reservation_id=OuterRef("pk"), email__iexact=email)
    return queryset.annotate(
        is_attendee=Exists(attending),
        is_organizer=Case(
            When(organizer_id=user.pk, then=Value(True)),
            default=Value(False),
            output_field=BooleanField(),
        ),
    )


def personal_meetings(user):
    # EXISTS avoids duplicate rows even when legacy attendee addresses differ only in case.
    return with_meeting_membership(Reservation.objects.filter(kind=Reservation.Kind.BOOKING), user).filter(
        Q(is_organizer=True) | Q(is_attendee=True)
    )
