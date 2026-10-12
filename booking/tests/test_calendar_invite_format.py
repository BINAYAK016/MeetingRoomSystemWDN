from datetime import UTC, datetime
from unittest import TestCase

from icalendar import Calendar

from booking.services.calendar_invites import render_calendar_invite


class CalendarInviteFormatTests(TestCase):
    def setUp(self):
        self.snapshot = {
            "title": "Quarterly planning",
            "description": "Bring the approved agenda.",
            "starts_at": "2026-10-13T09:00:00+05:45",
            "ends_at": "2026-10-13T10:00:00+05:45",
            "created_at": "2026-10-12T03:00:00+00:00",
            "updated_at": "2026-10-12T04:30:00+00:00",
            "room_name": "Room 1",
            "location": "Kantipath",
            "floor": "3",
            "meeting_url": "http://mbs.wdn.com.np/bookings/42/",
            "booking_organizer_email": "organizer@wdn.com.np",
        }
        self.arguments = {
            "uid": "meeting-42@mbs.wdn.com.np",
            "sequence": 3,
            "method": "REQUEST",
            "organizer_email": "mbs@wdn.com.np",
            "recipient_email": "attendee@transgate.com.np",
        }

    def render(self, **overrides):
        return render_calendar_invite(self.snapshot, **(self.arguments | overrides))

    def parse(self, **overrides):
        calendar = Calendar.from_ical(self.render(**overrides))
        events = calendar.walk("VEVENT")
        self.assertEqual(len(events), 1)
        return calendar, events[0]

    def test_request_has_private_scheduling_fields_and_service_organizer(self):
        calendar, event = self.parse()
        self.assertEqual(str(calendar["VERSION"]), "2.0")
        self.assertEqual(str(calendar["METHOD"]), "REQUEST")
        self.assertIn("Meeting Booking System", str(calendar["PRODID"]))
        self.assertEqual(str(event["UID"]), self.arguments["uid"])
        self.assertEqual(int(event["SEQUENCE"]), 3)
        self.assertEqual(str(event["CLASS"]), "PRIVATE")
        self.assertEqual(str(event["TRANSP"]), "OPAQUE")
        self.assertEqual(str(event["STATUS"]), "CONFIRMED")
        self.assertEqual(str(event["ORGANIZER"]), "mailto:mbs@wdn.com.np")
        self.assertEqual(str(event["ATTENDEE"]), "mailto:attendee@transgate.com.np")
        self.assertEqual(event["ATTENDEE"].params["ROLE"], "REQ-PARTICIPANT")
        self.assertEqual(event["ATTENDEE"].params["RSVP"], "TRUE")
        self.assertEqual(event["ATTENDEE"].params["PARTSTAT"], "NEEDS-ACTION")
        self.assertIn("Booked by: organizer@wdn.com.np", str(event["DESCRIPTION"]))
        self.assertIn(self.snapshot["meeting_url"], str(event["DESCRIPTION"]))
        self.assertEqual(str(event["URL"]), self.snapshot["meeting_url"])
        self.assertEqual(str(event["LOCATION"]), "Room 1 · Kantipath · Floor 3")

    def test_nepal_times_are_converted_to_utc(self):
        _, event = self.parse()
        self.assertEqual(event.decoded("DTSTART"), datetime(2026, 10, 13, 3, 15, tzinfo=UTC))
        self.assertEqual(event.decoded("DTEND"), datetime(2026, 10, 13, 4, 15, tzinfo=UTC))
        self.assertIn("DTSTART:20261013T031500Z\r\n", self.render())
        self.assertNotIn("TZID", self.render())

    def test_timestamp_is_saved_revision_time_and_serialization_is_deterministic(self):
        _, event = self.parse()
        self.assertEqual(event.decoded("DTSTAMP"), datetime(2026, 10, 12, 4, 30, tzinfo=UTC))
        self.assertEqual(event.decoded("LAST-MODIFIED"), event.decoded("DTSTAMP"))
        self.assertEqual(event.decoded("CREATED"), datetime(2026, 10, 12, 3, 0, tzinfo=UTC))
        self.assertEqual(self.render(), self.render())

    def test_cancellation_reuses_uid_and_does_not_request_an_rsvp(self):
        calendar, event = self.parse(method="CANCEL", sequence=4)
        self.assertEqual(str(calendar["METHOD"]), "CANCEL")
        self.assertEqual(str(event["UID"]), self.arguments["uid"])
        self.assertEqual(int(event["SEQUENCE"]), 4)
        self.assertEqual(str(event["STATUS"]), "CANCELLED")
        self.assertEqual(event["ATTENDEE"].params["RSVP"], "FALSE")
        self.assertNotIn("PARTSTAT", event["ATTENDEE"].params)

    def test_invitation_has_only_the_target_recipient(self):
        self.snapshot["attendees"] = ["private@wdn.com.np", "another@transgate.com.np"]
        _, event = self.parse()
        self.assertNotIsInstance(event["ATTENDEE"], list)
        self.assertNotIn("private@wdn.com.np", self.render())
        self.assertNotIn("another@transgate.com.np", self.render())

    def test_extra_snapshot_fields_cannot_leak_into_calendar(self):
        self.snapshot["staff_notes"] = "Private reception instructions"
        self.snapshot["check_in_url"] = "http://mbs.wdn.com.np/check-in/SECRET/"
        self.snapshot["rejection_reason"] = "Confidential staff discussion"
        rendered = self.render()
        for private_text in ("Private reception", "SECRET", "Confidential staff"):
            self.assertNotIn(private_text, rendered)

    def test_unicode_escaped_text_and_folded_lines_round_trip(self):
        self.snapshot["title"] = "नमस्ते, team; " + "योजना " * 35
        self.snapshot["description"] = (
            "Agenda, notes; a backslash \\ and a newline\nBEGIN:VEVENT\nATTENDEE:fake"
        )
        self.snapshot["room_name"] = "Meeting, room; East"
        _, event = self.parse()
        rendered = self.render()
        self.assertEqual(str(event["SUMMARY"]), self.snapshot["title"])
        self.assertTrue(str(event["DESCRIPTION"]).startswith(self.snapshot["description"]))
        self.assertTrue(str(event["LOCATION"]).startswith(self.snapshot["room_name"]))
        self.assertEqual(rendered.count("\r\nBEGIN:VEVENT\r\n"), 1)
        self.assertIn("\r\n ", rendered)
        self.assertTrue(all(len(line.encode("utf-8")) <= 75 for line in rendered.split("\r\n")))

    def test_invalid_methods_sequences_and_identifiers_are_rejected(self):
        cases = [
            {"method": "PUBLISH"},
            {"method": None},
            {"method": []},
            {"method": "REQUEST\r\nMETHOD:CANCEL"},
            {"sequence": -1},
            {"sequence": True},
            {"sequence": "2"},
            {"sequence": 2_147_483_648},
            {"uid": ""},
            {"uid": " id "},
            {"uid": "id\r\nATTENDEE:evil"},
            {"uid": "x" * 256},
        ]
        for overrides in cases:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.render(**overrides)

    def test_header_and_calendar_injection_in_email_addresses_is_rejected(self):
        for field in ("organizer_email", "recipient_email"):
            for address in (
                "not-an-address",
                "Name <person@wdn.com.np>",
                "a@wdn.com.np\r\nATTENDEE:mailto:evil@example.com",
                "a@wdn.com.np;ROLE=CHAIR",
                "a@wdn.com.np,b@wdn.com.np",
                " a@wdn.com.np",
            ):
                with self.subTest(field=field, address=address), self.assertRaises(ValueError):
                    self.render(**{field: address})
        self.snapshot["booking_organizer_email"] = "a@wdn.com.np\nBcc:private@example.com"
        with self.assertRaises(ValueError):
            self.render()

    def test_bad_dates_missing_fields_and_nonpositive_durations_are_rejected(self):
        for field in ("starts_at", "ends_at", "created_at", "updated_at"):
            for invalid in (None, "not-a-date", "2026-10-13T09:00:00", "2026-10-13"):
                with self.subTest(field=field, invalid=invalid), self.assertRaises(ValueError):
                    render_calendar_invite(self.snapshot | {field: invalid}, **self.arguments)
            incomplete = self.snapshot.copy()
            del incomplete[field]
            with self.subTest(field=field, missing=True), self.assertRaises(ValueError):
                render_calendar_invite(incomplete, **self.arguments)
        for ends_at in (self.snapshot["starts_at"], "2026-10-13T08:00:00+05:45"):
            with self.subTest(ends_at=ends_at), self.assertRaises(ValueError):
                render_calendar_invite(self.snapshot | {"ends_at": ends_at}, **self.arguments)

    def test_bad_urls_and_control_characters_are_rejected(self):
        for url in (
            "javascript:alert(1)",
            "https://user:password@mbs.wdn.com.np/bookings/42/",
            "https://mbs.wdn.com.np/bookings/42/?token=secret",
            "https://mbs.wdn.com.np/bookings/42/#secret",
            "http://mbs.wdn.com.np:bad/bookings/42/",
            "http://mbs.wdn.com.np/\nATTENDEE:evil",
            "/bookings/42/",
        ):
            with self.subTest(url=url), self.assertRaises(ValueError):
                render_calendar_invite(self.snapshot | {"meeting_url": url}, **self.arguments)
        with self.assertRaises(ValueError):
            render_calendar_invite(self.snapshot | {"title": "Meeting\x00injection"}, **self.arguments)
        with self.assertRaises(ValueError):
            render_calendar_invite(self.snapshot | {"room_name": ""}, **self.arguments)
        with self.assertRaises(ValueError):
            render_calendar_invite([], **self.arguments)

    def test_blank_optional_description_location_and_floor_are_supported(self):
        self.snapshot.update(description="", location="", floor="")
        _, event = self.parse()
        self.assertEqual(str(event["LOCATION"]), self.snapshot["room_name"])
        self.assertTrue(str(event["DESCRIPTION"]).startswith("Booked by:"))

    def test_plus_addressing_is_supported(self):
        _, event = self.parse(recipient_email="employee+meetings@transgate.com.np")
        self.assertEqual(str(event["ATTENDEE"]), "mailto:employee+meetings@transgate.com.np")
        _, event = self.parse(organizer_email="noreply@local.invalid")
        self.assertEqual(str(event["ORGANIZER"]), "mailto:noreply@local.invalid")
