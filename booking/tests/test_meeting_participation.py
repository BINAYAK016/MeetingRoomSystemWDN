from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django.test import TestCase, override_settings
from django.urls import reverse

from booking.models import BookingAttendee, BookingPolicy, BookingSeries, Reservation, Room, User

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 8, 8, tzinfo=LOCAL_TZ)
DAY = date(2026, 10, 9)


@override_settings(
    EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend",
    EMPLOYEE_EMAIL_DOMAINS=("wdn.com.np", "transgate.com.np"),
)
class MeetingParticipationTests(TestCase):
    def setUp(self):
        self.clock = patch("django.utils.timezone.now", return_value=NOW)
        self.clock.start()
        self.addCleanup(self.clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.organizer = User.objects.create_user("organizer@wdn.com.np")
        self.attendee = User.objects.create_user("attendee@transgate.com.np")
        self.outsider = User.objects.create_user("unrelated@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.room = Room.objects.create(name="Project room", location="WDN", floor="3", capacity=12)
        self.booking = self.make_booking()
        BookingAttendee.objects.create(reservation=self.booking, email=self.attendee.email)
        self.client.force_login(self.attendee)

    def make_booking(self, status="pending", *, offset=0, **changes):
        begins = datetime(2026, 10, 9, 9, tzinfo=LOCAL_TZ) + timedelta(hours=offset * 2)
        finishes = begins + timedelta(hours=1)
        values = {
            "room": self.room,
            "organizer": self.organizer,
            "created_by": self.organizer,
            "kind": Reservation.Kind.BOOKING,
            "status": status,
            "starts_at": begins,
            "ends_at": finishes,
            "occupied_from": begins,
            "occupied_until": finishes + timedelta(minutes=15),
            "title": f"Project planning {offset}",
            "description": "Agenda shared with the meeting participants",
        }
        if status == "rejected":
            values.update(rejected_at=NOW, rejection_reason="Room unavailable")
        values.update(changes)
        return Reservation.objects.create(**values)

    def sign_in_staff(self, verified=True):
        self.client.force_login(self.staff)
        if verified:
            session = self.client.session
            session["staff_verified"] = True
            session["staff_auth_version"] = self.staff.auth_version
            session.save()

    def list_ids(self, **query):
        response = self.client.get(reverse("my-bookings"), query)
        self.assertEqual(response.status_code, 200)
        return [item.pk for item in response.context["bookings"]]

    def test_invited_pending_meeting_is_in_upcoming_and_dashboard(self):
        response = self.client.get(reverse("my-bookings"))
        self.assertEqual([item.pk for item in response.context["bookings"]], [self.booking.pk])
        self.assertEqual(
            response.context["summary"], {"upcoming": 1, "pending": 1, "organized": 0, "invited": 1}
        )
        meeting = list(response.context["bookings"])[0]
        self.assertTrue(meeting.is_attendee)
        self.assertFalse(meeting.is_organizer)
        home = self.client.get(reverse("home"))
        self.assertEqual(home.context["pending_count"], 1)
        Reservation.objects.filter(pk=self.booking.pk).update(status="approved")
        self.assertEqual(self.client.get(reverse("home")).context["upcoming_count"], 1)

    def test_invitee_detail_is_read_only_and_has_shared_meeting_information(self):
        response = self.client.get(reverse("booking-detail", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, self.booking.title)
        self.assertContains(response, self.booking.description)
        self.assertTrue(response.context["is_attendee"])
        self.assertFalse(response.context["is_organizer"])
        for key in ("can_edit", "can_cancel", "can_review", "can_manage"):
            self.assertFalse(response.context[key])
        for label in ("Edit booking", "Cancel booking", "Approve request", "Manual check-in"):
            self.assertNotContains(response, label)

    def test_invitee_cannot_open_or_submit_mutating_booking_routes(self):
        for method, route in (("get", "booking-edit"), ("post", "booking-edit"), ("post", "booking-cancel")):
            with self.subTest(method=method, route=route):
                response = getattr(self.client, method)(reverse(route, args=[self.booking.pk]), {})
                self.assertEqual(response.status_code, 404)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "pending")
        self.assertEqual(self.booking.revision, 1)

    def test_invitee_cannot_exclude_another_organizers_booking_in_edit_availability(self):
        response = self.client.get(
            reverse("booking-availability"),
            {
                "booking_id": self.booking.pk,
                "date": DAY.isoformat(),
                "start_time": "09:00",
                "end_time": "10:00",
            },
        )
        self.assertEqual(response.status_code, 404)
        self.assertFalse(response.json()["ok"])

    def test_invitee_cannot_use_staff_review_checkin_or_report_routes(self):
        for route in ("staff-booking-approve", "staff-booking-reject", "staff-checkin"):
            response = self.client.post(reverse(route, args=[self.booking.pk]), {"reason": "Denied"})
            self.assertRedirects(response, reverse("staff-login"))
        self.assertRedirects(self.client.get(reverse("staff-report-excel")), reverse("staff-login"))
        response = self.client.post(reverse("checkin-confirm"), {"booking_id": self.booking.pk})
        self.assertEqual(response.status_code, 400)
        self.booking.refresh_from_db()
        self.assertEqual(self.booking.status, "pending")

    def test_organizer_retains_management_even_when_also_listed_as_attendee(self):
        BookingAttendee.objects.create(reservation=self.booking, email=self.organizer.email)
        self.client.force_login(self.organizer)
        response = self.client.get(reverse("booking-detail", args=[self.booking.pk]))
        self.assertTrue(response.context["can_manage"])
        self.assertTrue(response.context["can_edit"])
        self.assertTrue(response.context["can_cancel"])
        self.assertTrue(response.context["is_organizer"])
        self.assertFalse(response.context["is_attendee"])
        self.assertEqual(self.list_ids(role="organizer"), [self.booking.pk])
        self.assertEqual(self.list_ids(role="attendee"), [])

    def test_only_verified_staff_can_manage_unrelated_meetings(self):
        self.sign_in_staff(verified=False)
        self.assertEqual(self.client.get(reverse("booking-detail", args=[self.booking.pk])).status_code, 404)
        BookingAttendee.objects.create(reservation=self.booking, email=self.staff.email)
        response = self.client.get(reverse("booking-detail", args=[self.booking.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.context["can_manage"])
        self.assertEqual(self.client.get(reverse("booking-edit", args=[self.booking.pk])).status_code, 404)
        self.sign_in_staff()
        response = self.client.get(reverse("booking-detail", args=[self.booking.pk]))
        self.assertTrue(response.context["can_manage"])
        self.assertTrue(response.context["can_review"])
        self.assertEqual(self.client.get(reverse("booking-edit", args=[self.booking.pk])).status_code, 200)

    def test_matching_is_case_insensitive_and_duplicate_addresses_do_not_duplicate_rows(self):
        BookingAttendee.objects.filter(reservation=self.booking).update(email=self.attendee.email.upper())
        BookingAttendee.objects.create(reservation=self.booking, email=self.attendee.email)
        response = self.client.get(reverse("my-bookings"))
        self.assertEqual(response.context["page_obj"].paginator.count, 1)
        self.assertEqual(response.context["summary"]["invited"], 1)
        self.assertEqual(self.client.get(reverse("booking-detail", args=[self.booking.pk])).status_code, 200)

    def test_membership_follows_current_list_and_removed_invitees_lose_access_immediately(self):
        BookingAttendee.objects.filter(reservation=self.booking).delete()
        self.assertEqual(self.list_ids(period="history"), [])
        self.assertEqual(self.client.get(reverse("booking-detail", args=[self.booking.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("home")).context["pending_count"], 0)
        BookingAttendee.objects.create(reservation=self.booking, email=self.outsider.email)
        self.client.force_login(self.outsider)
        self.assertEqual(self.list_ids(), [self.booking.pk])

    def test_an_employee_who_signs_up_after_the_invitation_can_see_the_meeting(self):
        email = "new.colleague@transgate.com.np"
        BookingAttendee.objects.create(reservation=self.booking, email=email.upper())
        newcomer = User.objects.create_user(email)
        self.client.force_login(newcomer)
        self.assertEqual(self.list_ids(), [self.booking.pk])

    def test_unrelated_employee_cannot_read_private_meeting_or_guess_identifiers(self):
        self.client.force_login(self.outsider)
        self.assertEqual(self.list_ids(period="history"), [])
        self.assertEqual(self.client.get(reverse("booking-detail", args=[self.booking.pk])).status_code, 404)
        self.assertEqual(self.client.get(reverse("booking-detail", args=[999999])).status_code, 404)
        self.assertEqual(self.client.get(reverse("home")).context["pending_count"], 0)

    def test_all_occurrences_and_statuses_are_visible_in_history_but_only_active_in_upcoming(self):
        series = BookingSeries.objects.create(
            room=self.room,
            organizer=self.organizer,
            created_by=self.organizer,
            frequency="weekly",
            first_date=DAY,
            last_date=DAY + timedelta(days=7),
        )
        all_ids = [self.booking.pk]
        active_ids = [self.booking.pk]
        Reservation.objects.filter(pk=self.booking.pk).update(series=series)
        for offset, status in enumerate(
            ("approved", "checked_in", "completed", "cancelled", "rejected", "no_show"), start=1
        ):
            item = self.make_booking(status, offset=offset, series=series)
            BookingAttendee.objects.create(reservation=item, email=self.attendee.email)
            all_ids.append(item.pk)
            if status in ("approved", "checked_in"):
                active_ids.append(item.pk)
        self.assertEqual(set(self.list_ids(period="history")), set(all_ids))
        self.assertEqual(self.list_ids(), active_ids)

    def test_ended_approved_meetings_are_only_in_history(self):
        begins = NOW - timedelta(hours=2)
        Reservation.objects.filter(pk=self.booking.pk).update(
            status="approved",
            starts_at=begins,
            ends_at=NOW - timedelta(hours=1),
            occupied_from=begins,
            occupied_until=NOW - timedelta(minutes=45),
        )
        self.assertEqual(self.list_ids(), [])
        self.assertEqual(self.list_ids(period="history"), [self.booking.pk])

    def test_role_search_status_and_pagination_filters_preserve_membership(self):
        own = self.make_booking("approved", offset=1, organizer=self.attendee, title="Budget sync")
        self.assertEqual(self.list_ids(role="organizer"), [own.pk])
        self.assertEqual(self.list_ids(role="attendee"), [self.booking.pk])
        self.assertEqual(self.list_ids(q="budget"), [own.pk])
        self.assertEqual(self.list_ids(status="pending"), [self.booking.pk])
        self.assertEqual(self.list_ids(role="unrecognized", status="blocked"), [self.booking.pk, own.pk])
        for offset in range(2, 28):
            item = self.make_booking(offset=offset)
            BookingAttendee.objects.create(reservation=item, email=self.attendee.email)
        response = self.client.get(
            reverse("my-bookings"), {"role": "attendee", "status": "pending", "q": "planning", "page": 2}
        )
        self.assertEqual(response.context["page_obj"].paginator.count, 27)
        self.assertEqual(len(response.context["bookings"]), 2)
        for expected in ("role=attendee", "status=pending", "q=planning"):
            self.assertIn(expected, response.context["page_query"])

    def test_attendees_have_calendar_detail_links_without_exposing_meetings_to_others(self):
        response = self.client.get(reverse("calendar"), {"date": DAY.isoformat(), "view": "day"})
        cells = [cell for slot in response.context["slots"] for cell in slot["cells"] if cell["occupied"]]
        self.assertTrue(cells)
        self.assertTrue(all(cell["can_open"] and cell["attending"] and not cell["own"] for cell in cells))
        self.assertContains(response, reverse("booking-detail", args=[self.booking.pk]))
        self.client.force_login(self.outsider)
        response = self.client.get(reverse("calendar"), {"date": DAY.isoformat(), "view": "day"})
        self.assertNotContains(response, reverse("booking-detail", args=[self.booking.pk]))
        self.assertNotContains(response, self.booking.description)

    def test_room_closures_never_enter_personal_meetings_or_booking_details(self):
        item = self.make_booking(
            "blocked", offset=1, kind="block", organizer=None, block_reason="Maintenance"
        )
        BookingAttendee.objects.create(reservation=item, email=self.attendee.email)
        self.assertEqual(self.list_ids(period="history"), [self.booking.pk])
        self.assertEqual(self.client.get(reverse("booking-detail", args=[item.pk])).status_code, 404)


@override_settings(EMPLOYEE_EMAIL_DOMAINS=("wdn.com.np", "transgate.com.np"))
class AttendeeDirectoryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("requester@wdn.com.np")
        self.client.force_login(self.user)
        self.endpoint = reverse("attendee-suggestions")

    def request(self, query="", **params):
        return self.client.get(self.endpoint, {"q": query, **params})

    def test_authentication_and_get_only(self):
        self.client.logout()
        self.assertEqual(self.request("bi").status_code, 401)
        self.client.force_login(self.user)
        self.assertEqual(self.client.post(self.endpoint, {"q": "bi"}).status_code, 405)
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.request("bi").status_code, 401)

    def test_requester_must_have_current_approved_company_domain(self):
        outsider = User.objects.create_user("requester@example.com")
        self.client.force_login(outsider)
        self.assertEqual(self.request("re").status_code, 403)
        self.client.force_login(self.user)
        with override_settings(EMPLOYEE_EMAIL_DOMAINS=("transgate.com.np",)):
            self.assertEqual(self.request("re").status_code, 403)

    def test_short_queries_do_not_dump_accounts_and_queries_are_bounded(self):
        User.objects.create_user("binayak@wdn.com.np")
        for query in ("", "b", " b "):
            with self.subTest(query=query):
                self.assertEqual(self.request(query).json(), {"ok": True, "results": []})
        self.assertEqual(self.request("b" * 101).status_code, 400)
        self.assertEqual(self.request("%_").json()["results"], [])

    def test_results_only_contain_safe_email_and_name_fields_with_no_staff_metadata(self):
        person = User.objects.create_user(
            "binayak@wdn.com.np",
            "private-password",
            first_name="Binayak",
            last_name="Bhandari",
            department="Private department",
            is_staff=True,
            is_superuser=True,
        )
        response = self.request("BI")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(), {"ok": True, "results": [{"email": person.email, "name": "Binayak Bhandari"}]}
        )
        self.assertIn("no-store", response["Cache-Control"])
        for secret in (
            "private-password",
            "Private department",
            "is_staff",
            "auth_version",
            "password",
            '"id"',
        ):
            self.assertNotIn(secret, response.content.decode())

    def test_prefix_matches_email_first_or_last_name_but_not_email_substrings(self):
        person = User.objects.create_user(
            "someone@transgate.com.np", first_name="Palina", last_name="Shrestha"
        )
        for query in ("so", " pa ", "shr"):
            with self.subTest(query=query):
                self.assertEqual(self.request(query).json()["results"][0]["email"], person.email)
        self.assertEqual(self.request("meone").json()["results"], [])
        self.assertEqual(self.request("@transgate").json()["results"], [])

    def test_inactive_and_disallowed_or_lookalike_domains_are_excluded(self):
        User.objects.create_user("billing@wdn.com.np", is_active=False)
        User.objects.create_user("billing@example.com")
        User.objects.create_user("billing@evilwdn.com.np")
        User.objects.create_user("billing@wdn.com.np.example.com")
        approved = User.objects.create_user("billing@transgate.com.np")
        self.assertEqual(self.request("bi").json()["results"], [{"email": approved.email, "name": ""}])

    def test_limit_and_order_are_fixed_and_client_cannot_request_dump_pages(self):
        for number in reversed(range(12)):
            User.objects.create_user(f"colleague{number:02}@wdn.com.np")
        response = self.request("co", limit="999999", page="2")
        self.assertEqual(len(response.json()["results"]), 8)
        self.assertEqual(
            [item["email"] for item in response.json()["results"]],
            [f"colleague{number:02}@wdn.com.np" for number in range(8)],
        )

    def test_current_domain_allowlist_and_case_normalization_are_respected(self):
        person = User.objects.create(email="BILLING@TRANSgate.COM.np")
        self.assertEqual(self.request("bi").json()["results"], [{"email": person.email.lower(), "name": ""}])
        with override_settings(EMPLOYEE_EMAIL_DOMAINS=("wdn.com.np",)):
            self.assertEqual(self.request("bi").json()["results"], [])

    def test_booking_form_exposes_endpoint_url_for_progressive_enhancement(self):
        BookingPolicy.objects.get_or_create(pk=1)
        response = self.client.get(reverse("booking-new"))
        self.assertEqual(response.context["booking_ui"]["attendee_suggestions_url"], self.endpoint)
