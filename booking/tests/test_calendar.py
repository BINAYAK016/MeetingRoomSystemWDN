from datetime import date, datetime, time, timedelta
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.urls import reverse

from booking.models import BookingAttendee, BookingPolicy, CompanyHoliday, Reservation, Room, User

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 5, 8, tzinfo=LOCAL_TZ)
DAY = date(2026, 10, 6)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMPLOYEE_EMAIL_DOMAINS=("wdn.com.np", "transgate.com.np"),
)
class CalendarTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        self.policy, _ = BookingPolicy.objects.get_or_create(pk=1)
        self.employee = User.objects.create_user("calendar@transgate.com.np")
        self.organizer = User.objects.create_user("private.organizer@wdn.com.np")
        self.staff = User.objects.create_user("calendar.desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Calendar room", location="WDN", floor="3", capacity=12)
        self.other_room = Room.objects.create(name="Other active room", location="WDN", floor="4", capacity=8)
        self.inactive_room = Room.objects.create(
            name="Inactive room", location="WDN", floor="5", capacity=8, is_active=False
        )
        self.own = self.meeting(9, organizer=self.employee, title="My quarterly planning")
        self.invited = self.meeting(11, title="Invited project meeting")
        BookingAttendee.objects.create(reservation=self.invited, email=self.employee.email.upper())
        self.foreign = self.meeting(13, title="Confidential restructuring")
        self.pending = self.meeting(15, title="Private pending decision", status="pending")
        self.client.force_login(self.employee)

    def meeting(self, hour, *, room=None, day=DAY, organizer=None, duration=60, **changes):
        starts_at = datetime.combine(day, time(hour), LOCAL_TZ)
        ends_at = starts_at + timedelta(minutes=duration)
        values = {
            "room": room or self.room,
            "organizer": None if changes.get("kind") == "block" else (organizer or self.organizer),
            "created_by": organizer or self.organizer,
            "kind": Reservation.Kind.BOOKING,
            "status": Reservation.Status.APPROVED,
            "starts_at": starts_at,
            "ends_at": ends_at,
            "occupied_from": starts_at,
            "occupied_until": ends_at + timedelta(minutes=15),
            "title": "Calendar meeting",
            "description": "Confidential agenda unavailable to unrelated employees",
            "department": "Private department",
            "front_desk_notes": "Private operational notes",
        }
        values.update(changes)
        return Reservation.objects.create(**values)

    def response(self, *, selected=DAY, **params):
        return self.client.get(reverse("calendar"), {"date": selected.isoformat(), **params})

    def days(self, response):
        return [day for week in response.context["calendar"]["month_weeks"] for day in week["days"]]

    def events(self, response):
        calendar = response.context["calendar"]
        if response.context["view"] == "month":
            return [event for day in self.days(response) for event in day["events"]]
        if response.context["view"] == "week":
            return [event for day in calendar["week_days"] for event in day["events"]]
        return [event for column in calendar["day_columns"] for event in column["events"]]

    def verify_staff(self):
        self.client.force_login(self.staff)
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = self.staff.auth_version
        session.save()

    def test_calendar_requires_sign_in_and_only_accepts_get(self):
        self.client.logout()
        response = self.response()
        self.assertEqual(response.status_code, 302)
        self.assertTrue(response.url.startswith(reverse("sign-in")))
        self.client.force_login(self.employee)
        self.assertEqual(self.client.post(reverse("calendar")).status_code, 405)

    def test_month_is_default_and_available_to_employees(self):
        response = self.response()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["view"], "month")
        self.assertEqual(response.context["calendar"]["title"], "October 2026")
        self.assertTrue(response.context["calendar"]["month_weeks"])
        self.assertContains(response, self.own.title)

    def test_month_is_a_padded_monday_to_sunday_grid(self):
        response = self.response(view="month")
        weeks = response.context["calendar"]["month_weeks"]
        self.assertTrue(all(len(week["days"]) == 7 for week in weeks))
        days = self.days(response)
        self.assertEqual(days[0]["date"], date(2026, 9, 28))
        self.assertEqual(days[-1]["date"], date(2026, 11, 1))
        self.assertEqual(
            [day["date"] for day in days], [days[0]["date"] + timedelta(days=i) for i in range(35)]
        )
        self.assertTrue(days[0]["outside_month"])
        self.assertFalse(next(day for day in days if day["date"] == DAY)["outside_month"])

    def test_month_handles_leap_day_and_cross_year_padding(self):
        for selected, expected_first, expected_last, day_count in (
            (date(2028, 2, 10), date(2028, 1, 31), date(2028, 3, 5), 29),
            (date(2027, 1, 10), date(2026, 12, 28), date(2027, 1, 31), 31),
            (date(2026, 12, 10), date(2026, 11, 30), date(2027, 1, 3), 31),
        ):
            with (
                self.subTest(selected=selected),
                patch(
                    "django.utils.timezone.now", return_value=datetime.combine(selected, time(8), LOCAL_TZ)
                ),
            ):
                self.client.force_login(self.employee)
                response = self.response(selected=selected, view="month")
                self.assertEqual(response.status_code, 200)
                days = self.days(response)
                self.assertEqual(days[0]["date"], expected_first)
                self.assertEqual(days[-1]["date"], expected_last)
                self.assertEqual(sum(not day["outside_month"] for day in days), day_count)
                self.assertTrue(
                    all(
                        week["days"][0]["date"].weekday() == 0
                        for week in response.context["calendar"]["month_weeks"]
                    )
                )

    def test_month_navigation_clamps_to_the_last_day_and_preserves_room(self):
        with patch("django.utils.timezone.now", return_value=datetime(2026, 1, 20, 8, tzinfo=LOCAL_TZ)):
            response = self.response(selected=date(2026, 1, 31), room=self.room.pk)
        calendar = response.context["calendar"]
        for key, expected in (("previous_url", "2025-12-31"), ("next_url", "2026-02-28")):
            query = parse_qs(urlsplit(calendar[key]).query)
            self.assertEqual(query["date"], [expected])
            self.assertEqual(query["room"], [str(self.room.pk)])
            self.assertEqual(query["view"], ["month"])

    def test_today_and_view_links_preserve_the_selected_room(self):
        response = self.response(room=self.room.pk, view="week")
        calendar = response.context["calendar"]
        for key, expected_view in (
            ("today_url", "week"),
            ("month_url", "month"),
            ("week_url", "week"),
            ("day_url", "day"),
        ):
            query = parse_qs(urlsplit(calendar[key]).query)
            self.assertEqual(query["room"], [str(self.room.pk)])
            self.assertEqual(query["view"], [expected_view])
        self.assertEqual(parse_qs(urlsplit(calendar["today_url"]).query)["date"], [NOW.date().isoformat()])

    def test_week_contains_event_cards_and_full_monday_to_sunday_dates(self):
        response = self.response(view="week")
        days = response.context["calendar"]["week_days"]
        self.assertEqual(
            [day["date"] for day in days], [date(2026, 10, 5) + timedelta(days=i) for i in range(7)]
        )
        meeting_day = next(day for day in days if day["date"] == DAY)
        self.assertEqual(len([event for event in meeting_day["events"] if event["kind"] == "booking"]), 4)
        self.assertContains(response, self.invited.title)
        self.assertNotContains(response, self.foreign.title)

    def test_room_filter_limits_every_view_and_never_includes_inactive_rooms(self):
        other = self.meeting(9, room=self.other_room, organizer=self.employee, title="Other room booking")
        hidden = self.meeting(
            9, room=self.inactive_room, organizer=self.employee, title="Inactive hidden meeting"
        )
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view, room=self.room.pk)
                self.assertEqual([room.pk for room in response.context["calendar_rooms"]], [self.room.pk])
                self.assertEqual(response.context["calendar"]["selected_room_id"], str(self.room.pk))
                self.assertNotContains(response, other.title)
                self.assertNotContains(response, reverse("booking-detail", args=[other.pk]))
                self.assertNotContains(response, hidden.title)
                self.assertNotContains(response, self.inactive_room.name)
                self.assertNotContains(response, reverse("booking-detail", args=[hidden.pk]))

    def test_unrelated_bookings_are_masked_in_html_and_presenter_in_every_view(self):
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                for item in (self.foreign, self.pending):
                    self.assertNotContains(response, item.title)
                    self.assertNotContains(response, reverse("booking-detail", args=[item.pk]))
                for private in (
                    self.organizer.email,
                    self.foreign.description,
                    self.foreign.department,
                    self.foreign.front_desk_notes,
                ):
                    self.assertNotContains(response, private)
                events = self.events(response)
                hidden = [event for event in events if event["title"] in ("Busy", "Pending approval")]
                self.assertTrue(hidden)
                for event in hidden:
                    self.assertFalse(event["url"])
                    for unsafe in ("id", "pk", "reservation", "organizer", "description", "attendees"):
                        self.assertNotIn(unsafe, event)
                self.assertContains(response, self.own.title)
                self.assertContains(response, reverse("booking-detail", args=[self.own.pk]))
                self.assertContains(response, self.invited.title)
                self.assertContains(response, reverse("booking-detail", args=[self.invited.pk]))

    def test_removed_attendee_loses_calendar_title_and_link_immediately(self):
        BookingAttendee.objects.filter(reservation=self.invited).delete()
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                self.assertNotContains(response, self.invited.title)
                self.assertNotContains(response, reverse("booking-detail", args=[self.invited.pk]))
                self.assertContains(response, self.own.title)

    def test_verified_staff_can_open_foreign_meetings_but_unverified_staff_cannot(self):
        self.client.force_login(self.staff)
        for view in ("month", "week", "day"):
            response = self.response(view=view)
            self.assertNotContains(response, self.foreign.title)
            self.assertNotContains(response, reverse("booking-detail", args=[self.foreign.pk]))
            self.assertContains(response, reverse("staff-login"))
            self.assertNotContains(response, f'href="{reverse("staff-dashboard")}"')
        self.verify_staff()
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                self.assertContains(response, self.foreign.title)
                self.assertContains(response, reverse("booking-detail", args=[self.foreign.pk]))
                self.assertContains(response, self.pending.title)
                self.assertContains(response, f'href="{reverse("staff-dashboard")}"')

    def test_month_overflow_keeps_all_events_including_private_occupancy(self):
        response = self.response()
        meeting_day = next(day for day in self.days(response) if day["date"] == DAY)
        self.assertEqual(len([event for event in meeting_day["events"] if event["kind"] == "booking"]), 4)
        self.assertEqual(meeting_day["visible_events"], meeting_day["events"][:3])
        self.assertEqual(meeting_day["more_events"], meeting_day["events"][3:])
        self.assertEqual(meeting_day["extra_count"], len(meeting_day["more_events"]))

    def test_cancelled_no_show_rejected_and_cancelled_closures_do_not_occupy_calendar(self):
        for status in ("cancelled", "no_show", "rejected"):
            changes = {"status": status, "organizer": self.employee, "title": f"Excluded {status}"}
            if status == "rejected":
                changes.update(rejected_at=NOW, rejection_reason="No longer needed")
            item = self.meeting(10, room=self.other_room, **changes)
            for view in ("month", "week", "day"):
                with self.subTest(status=status, view=view):
                    response = self.response(view=view)
                    self.assertNotContains(response, item.title)
                    self.assertNotContains(response, reverse("booking-detail", args=[item.pk]))
        closed = self.meeting(
            10,
            room=self.other_room,
            kind="block",
            status="block_cancelled",
            organizer=None,
            block_reason="Cancelled closure",
            title="",
        )
        for view in ("month", "week", "day"):
            response = self.response(view=view)
            self.assertNotContains(response, reverse("booking-detail", args=[closed.pk]))
            self.assertFalse(any(event["kind"] == "closure" for event in self.events(response)))

    def test_weekend_holiday_past_and_horizon_days_do_not_offer_booking_actions(self):
        CompanyHoliday.objects.create(date=date(2026, 10, 7), name="Company celebration")
        response = self.response()
        days = {day["date"]: day for day in self.days(response)}
        for selected, reason in (
            (date(2026, 10, 10), "weekend"),
            (date(2026, 10, 7), "Company celebration"),
            (date(2026, 10, 2), "Past date"),
            (date(2026, 10, 20), "booking window"),
        ):
            with self.subTest(selected=selected):
                self.assertIn(reason, days[selected]["booking_reason"])
                self.assertFalse(days[selected]["new_booking_url"])
                day_response = self.response(selected=selected, view="day")
                self.assertTrue(
                    all(
                        not cell["available"]
                        for slot in day_response.context["slots"]
                        for cell in slot["cells"]
                    )
                )
        self.assertTrue(days[date(2026, 10, 19)]["new_booking_url"])

    def test_day_slots_preserve_exact_buffer_and_minimum_meeting_boundaries(self):
        response = self.response(view="day", room=self.room.pk)
        cells = {slot["time"].time(): slot["cells"][0] for slot in response.context["slots"]}
        self.assertFalse(cells[time(10)]["available"])
        self.assertTrue(cells[time(10)]["can_open"])
        self.assertEqual(cells[time(10)]["occupied"]["url"], reverse("booking-detail", args=[self.own.pk]))
        self.assertEqual(cells[time(10)]["occupied"]["kind"], "buffer")
        self.assertEqual(cells[time(10)]["occupied"]["title"], "Meeting buffer")
        self.assertEqual(cells[time(10)]["occupied"]["css_class"], "calendar-event-buffer")
        self.assertTrue(cells[time(10)]["show_event"])
        self.assertEqual(cells[time(14)]["occupied"]["title"], "Meeting buffer")
        self.assertEqual(cells[time(14)]["occupied"]["url"], "")
        self.assertTrue(cells[time(10, 15)]["available"])
        self.assertFalse(cells[time(10, 30)]["available"])
        self.assertIn("buffer", cells[time(10, 30)]["unavailable_reason"])
        self.assertFalse(cells[time(16, 45)]["available"])
        self.assertIn("closing", cells[time(16, 45)]["unavailable_reason"])
        for selected_time in (time(10, 15), time(12, 15), time(14, 15)):
            query = parse_qs(urlsplit(cells[selected_time]["booking_url"]).query)
            self.assertEqual(query["room"], [str(self.room.pk)])
            self.assertEqual(query["date"], [DAY.isoformat()])
            self.assertEqual(query["start"], [selected_time.strftime("%H:%M")])

    def test_day_closures_are_busy_and_never_link_to_booking_details(self):
        closure = self.meeting(
            9,
            room=self.other_room,
            kind="block",
            status="blocked",
            organizer=None,
            block_reason="Internal private maintenance reason",
            title="",
        )
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                self.assertNotContains(response, reverse("booking-detail", args=[closure.pk]))
                self.assertNotContains(response, closure.block_reason)
                closure_events = [event for event in self.events(response) if event["kind"] == "closure"]
                self.assertTrue(closure_events)
                self.assertTrue(all(not event["url"] for event in closure_events))
        response = self.response(view="day", room=self.other_room.pk)
        occupied = [cell for slot in response.context["slots"] for cell in slot["cells"] if cell["occupied"]]
        self.assertTrue(occupied)
        self.assertTrue(all(not cell["available"] and not cell["can_open"] for cell in occupied))

    def test_calendar_titles_are_escaped_for_participants(self):
        self.own.title = '<script>alert("calendar")</script>'
        self.own.save(update_fields=["title"])
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                self.assertContains(response, "&lt;script&gt;")
                self.assertNotContains(response, self.own.title)

    def test_month_event_with_buffer_in_next_day_is_not_duplicated_as_a_meeting(self):
        begins = datetime(2026, 10, 8, 23, 30, tzinfo=LOCAL_TZ)
        item = self.meeting(
            9,
            room=self.other_room,
            organizer=self.employee,
            title="Late override meeting",
            starts_at=begins,
            ends_at=begins + timedelta(minutes=30),
            occupied_from=begins,
            occupied_until=begins + timedelta(minutes=45),
        )
        response = self.response()
        events = [
            event
            for day in self.days(response)
            for event in day["events"]
            if event["url"] == reverse("booking-detail", args=[item.pk]) and event["kind"] == "booking"
        ]
        self.assertEqual(len(events), 1)

    def test_invalid_room_filters_fall_back_to_the_active_room_snapshot(self):
        for room in ("invalid", "-1", "999999999999999999999999999", str(self.inactive_room.pk)):
            with self.subTest(room=room):
                response = self.response(room=room)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["calendar"]["selected_room_id"], "")
                self.assertEqual(
                    [item.pk for item in response.context["calendar_rooms"]],
                    [self.room.pk, self.other_room.pk],
                )
                self.assertNotContains(response, self.inactive_room.name)

    def test_invalid_view_and_out_of_range_dates_fall_back_without_errors(self):
        for selected in ("invalid", "2026-02-30", "10000-01-01", "2025-01-01", "2028-01-01"):
            with self.subTest(selected=selected):
                response = self.client.get(reverse("calendar"), {"date": selected, "view": "invalid"})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["view"], "month")
                self.assertEqual(response.context["selected"], NOW.date())

    def test_date_navigation_stays_within_the_calendar_display_limit(self):
        response = self.response(selected=NOW.date() + timedelta(days=366), view="day")
        self.assertFalse(response.context["calendar"]["next_url"])
        self.assertTrue(response.context["calendar"]["previous_url"])
        response = self.response(selected=NOW.date() - timedelta(days=366), view="day")
        self.assertFalse(response.context["calendar"]["previous_url"])
        self.assertTrue(response.context["calendar"]["next_url"])

    def test_no_active_rooms_renders_a_helpful_empty_state(self):
        Room.objects.update(is_active=False)
        for view in ("month", "week", "day"):
            with self.subTest(view=view):
                response = self.response(view=view)
                self.assertEqual(response.status_code, 200)
                self.assertFalse(response.context["calendar_rooms"])
                self.assertContains(response, "No active meeting rooms")
                self.assertNotContains(response, self.own.title)

    def test_month_and_week_use_one_active_room_snapshot_during_activation(self):
        hidden = self.meeting(
            9, room=self.inactive_room, organizer=self.employee, title="Activated later meeting"
        )
        original_filter = Reservation.objects.filter

        def activate_before_booking_query(*args, **kwargs):
            Room.objects.filter(pk=self.inactive_room.pk).update(is_active=True)
            return original_filter(*args, **kwargs)

        for view in ("month", "week"):
            Room.objects.filter(pk=self.inactive_room.pk).update(is_active=False)
            with (
                self.subTest(view=view),
                patch(
                    "booking.calendar_presenter.Reservation.objects.filter",
                    side_effect=activate_before_booking_query,
                ),
            ):
                response = self.response(view=view)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(
                    [room.pk for room in response.context["rooms"]], [self.room.pk, self.other_room.pk]
                )
                self.assertNotContains(response, hidden.title)
                self.assertNotContains(response, reverse("booking-detail", args=[hidden.pk]))
                self.assertNotContains(response, self.inactive_room.name)
            refreshed = self.response(view=view)
            self.assertContains(refreshed, hidden.title)
