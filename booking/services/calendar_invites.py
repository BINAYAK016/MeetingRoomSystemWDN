"""Serialize a saved booking snapshot as a private, recipient-specific invitation."""

from datetime import UTC, datetime
from email.headerregistry import Address
from urllib.parse import urlsplit

from icalendar import Calendar, Event, vCalAddress

PRODID = "-//Transgate Tech//Meeting Booking System//EN"
MAX_SEQUENCE = 2_147_483_647


def _email(value, field):
    """Accept a bare mailbox, never an address header or an injected iCal field."""
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(ord(char) < 33 or ord(char) == 127 for char in value)
        or any(char in value for char in ':;,<>"\\')
    ):
        raise ValueError(f"{field} must be a bare email address")
    try:
        address = Address(addr_spec=value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a bare email address") from exc
    if not address.username or not address.domain or address.addr_spec != value:
        raise ValueError(f"{field} must be a bare email address")
    return value


def _timestamp(snapshot, field):
    value = snapshot.get(field)
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an aware ISO datetime")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be an aware ISO datetime") from exc
    if parsed.utcoffset() is None:
        raise ValueError(f"{field} must be an aware ISO datetime")
    return parsed.astimezone(UTC)


def _text(snapshot, field, *, required=False):
    value = snapshot.get(field, "")
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"{field} must be {'nonempty ' if required else ''}text")
    # Newlines and tabs are ordinary meeting text; the library escapes/folds them.
    if any(ord(char) < 32 and char not in "\r\n\t" for char in value) or "\x7f" in value:
        raise ValueError(f"{field} contains a control character")
    return value.replace("\r\n", "\n").replace("\r", "\n")


def _meeting_url(snapshot):
    value = _text(snapshot, "meeting_url", required=True)
    if any(char.isspace() for char in value):
        raise ValueError("meeting_url must be a plain HTTP or HTTPS booking URL")
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"http", "https"}
            and parsed.hostname
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
        )
        # Accessing port also validates a malformed or out-of-range port number.
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("meeting_url must be a plain HTTP or HTTPS booking URL") from exc
    if not valid:
        raise ValueError("meeting_url must be a plain HTTP or HTTPS booking URL")
    return value


def render_calendar_invite(
    snapshot: dict,
    *,
    uid: str,
    sequence: int,
    method: str,
    organizer_email: str,
    recipient_email: str,
) -> str:
    """Render REQUEST/CANCEL without database access, clocks, or SMTP side effects.

    The caller supplies a persisted UID/revision and safe booking-detail URL. Each
    message includes only its recipient as ATTENDEE; staff copies are not invites.
    Snapshot allowlisting keeps staff notes and email check-in links out of ICS.
    """
    if not isinstance(snapshot, dict):
        raise ValueError("snapshot must be a dictionary")
    if not isinstance(method, str) or method not in {"REQUEST", "CANCEL"}:
        raise ValueError("method must be REQUEST or CANCEL")
    if type(sequence) is not int or not 0 <= sequence <= MAX_SEQUENCE:
        raise ValueError("sequence must be a nonnegative RFC 5545 integer")
    if (
        not isinstance(uid, str)
        or not uid.strip()
        or uid != uid.strip()
        or len(uid.encode("utf-8")) > 255
        or any(ord(char) < 32 or ord(char) == 127 for char in uid)
    ):
        raise ValueError("uid must be a stable identifier without control characters")

    organizer_email = _email(organizer_email, "organizer_email")
    recipient_email = _email(recipient_email, "recipient_email")
    booked_by = _email(snapshot.get("booking_organizer_email"), "booking_organizer_email")
    starts_at = _timestamp(snapshot, "starts_at")
    ends_at = _timestamp(snapshot, "ends_at")
    updated_at = _timestamp(snapshot, "updated_at")
    created_at = _timestamp(snapshot, "created_at")
    if ends_at <= starts_at:
        raise ValueError("ends_at must be later than starts_at")

    title = _text(snapshot, "title", required=True)
    description = _text(snapshot, "description")
    room_name = _text(snapshot, "room_name", required=True)
    location = _text(snapshot, "location")
    floor = _text(snapshot, "floor")
    meeting_url = _meeting_url(snapshot)
    location_parts = [room_name, location, f"Floor {floor}" if floor else ""]
    description_parts = [description, f"Booked by: {booked_by}", f"Meeting details: {meeting_url}"]

    calendar = Calendar()
    calendar.add("prodid", PRODID)
    calendar.add("version", "2.0")
    calendar.add("calscale", "GREGORIAN")
    calendar.add("method", method)

    event = Event()
    event.add("uid", uid)
    event.add("sequence", sequence)
    event.add("dtstamp", updated_at)
    event.add("created", created_at)
    event.add("last-modified", updated_at)
    event.add("dtstart", starts_at)
    event.add("dtend", ends_at)
    event.add("summary", title)
    event.add("description", "\n\n".join(part for part in description_parts if part))
    event.add("location", " · ".join(part for part in location_parts if part))
    event.add("url", meeting_url)
    event.add("class", "PRIVATE")
    event.add("transp", "OPAQUE")
    event.add("status", "CANCELLED" if method == "CANCEL" else "CONFIRMED")

    organizer = vCalAddress(f"mailto:{organizer_email}")
    organizer.params["CN"] = "Meeting Booking System"
    event.add("organizer", organizer)
    attendee = vCalAddress(f"mailto:{recipient_email}")
    attendee.params["ROLE"] = "REQ-PARTICIPANT"
    attendee.params["RSVP"] = "FALSE" if method == "CANCEL" else "TRUE"
    if method == "REQUEST":
        attendee.params["PARTSTAT"] = "NEEDS-ACTION"
    event.add("attendee", attendee)
    calendar.add_component(event)
    return calendar.to_ical().decode("utf-8")
