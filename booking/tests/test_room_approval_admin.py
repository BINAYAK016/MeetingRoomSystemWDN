from datetime import timedelta
from unittest.mock import patch

from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from booking.models import AuditEvent, Reservation, Room, User
from booking.services.auth_security import staff_session_verified


class RoomApprovalAdminTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(name="Office meeting room", location="WDN", floor="2", capacity=8)
        self.employee = User.objects.create_user("employee@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.login(self.client, self.staff)
        self.url = reverse("staff-room-approval", args=[self.room.pk])

    def login(self, client, user, *, verified=True, version=None):
        client.force_login(user)
        session = client.session
        session["staff_verified"] = verified
        session["staff_auth_version"] = user.auth_version if version is None else version
        session.save()

    def room_data(self, **changes):
        values = {
            "name": self.room.name,
            "location": self.room.location,
            "floor": self.room.floor,
            "capacity": self.room.capacity,
            "facilities_text": "",
            "is_active": "on",
        }
        values.update(changes)
        return values

    def test_room_list_contains_checked_control_csrf_and_save_fallback(self):
        response = self.client.get(reverse("staff-rooms"))
        self.assertContains(response, "Requires approval")
        self.assertContains(response, "data-room-approval-form")
        self.assertContains(response, f'action="{self.url}"')
        self.assertContains(response, 'name="csrfmiddlewaretoken"')
        self.assertContains(response, 'name="requires_approval" value="0"')
        self.assertContains(response, 'name="requires_approval" value="1" checked')
        self.assertContains(response, 'room-approval-save">Save</button>')
        self.assertNotIn("onchange=", response.content.decode())
        form = self.client.get(reverse("staff-room-new")).context["form"]
        self.assertIs(form["requires_approval"].value(), True)

    def test_unchecked_and_checked_submissions_persist_and_audit_only_changes(self):
        response = self.client.post(self.url, {"requires_approval": "0", "page": "2"})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse("staff-rooms") + "?page=2")
        self.room.refresh_from_db()
        self.assertFalse(self.room.requires_approval)
        event = AuditEvent.objects.get(action="room_approval_changed")
        self.assertEqual(event.actor, self.staff)
        self.assertEqual(event.target_type, "room")
        self.assertEqual(event.target_id, self.room.pk)
        self.assertEqual(event.details, {"old_requires_approval": True, "requires_approval": False})
        self.client.post(self.url, {"requires_approval": "0"})
        self.assertEqual(AuditEvent.objects.filter(action="room_approval_changed").count(), 1)
        response = self.client.post(self.url, {"requires_approval": ["0", "1"]})
        self.assertEqual(response.status_code, 302)
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)
        self.assertEqual(AuditEvent.objects.filter(action="room_approval_changed").count(), 2)

    def test_room_editor_saves_approval_flag_and_records_both_directions(self):
        url = reverse("staff-room-edit", args=[self.room.pk])
        self.assertIs(self.client.get(url).context["form"]["requires_approval"].value(), True)
        self.assertEqual(self.client.post(url, self.room_data()).status_code, 302)
        self.room.refresh_from_db()
        self.assertFalse(self.room.requires_approval)
        self.assertEqual(self.client.post(url, self.room_data(requires_approval="on")).status_code, 302)
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)
        self.assertEqual(AuditEvent.objects.filter(action="room_approval_changed").count(), 2)

    def test_new_room_can_explicitly_use_either_approval_setting(self):
        for required in (True, False):
            values = self.room_data(name=f"New room {required}")
            if required:
                values["requires_approval"] = "on"
            self.assertEqual(self.client.post(reverse("staff-room-new"), values).status_code, 302)
            self.assertEqual(Room.objects.get(name=values["name"]).requires_approval, required)

    def test_toggle_denies_anonymous_employees_unverified_and_stale_staff(self):
        clients = [Client()]
        for user, verified, version in (
            (self.employee, True, None),
            (self.staff, False, None),
            (self.staff, True, self.staff.auth_version + 1),
        ):
            client = Client()
            self.login(client, user, verified=verified, version=version)
            clients.append(client)
        for client in clients:
            with self.subTest(client=client):
                response = client.post(self.url, {"requires_approval": "0"})
                self.assertEqual(response.status_code, 302)
                self.assertEqual(response.url, reverse("staff-login"))
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)
        self.assertFalse(AuditEvent.objects.filter(action="room_approval_changed").exists())

    def test_deactivated_and_demoted_staff_sessions_cannot_toggle(self):
        for field in ("is_active", "is_staff"):
            user = User.objects.create_user(f"{field}@wdn.com.np", is_staff=True)
            client = Client()
            self.login(client, user)
            User.objects.filter(pk=user.pk).update(**{field: False})
            response = client.post(self.url, {"requires_approval": "0"})
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("staff-login"))
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)

    def test_access_revocation_after_initial_permission_check_is_rechecked_under_lock(self):
        def revoke_after_check(request):
            allowed = staff_session_verified(request)
            User.objects.filter(pk=self.staff.pk).update(is_staff=False)
            return allowed

        for url, values in (
            (self.url, {"requires_approval": "0"}),
            (reverse("staff-room-edit", args=[self.room.pk]), self.room_data()),
        ):
            User.objects.filter(pk=self.staff.pk).update(is_staff=True)
            with patch("booking.staff_views.staff_session_verified", side_effect=revoke_after_check):
                response = self.client.post(url, values)
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("staff-login"))
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)
        self.assertFalse(AuditEvent.objects.filter(action="room_approval_changed").exists())

    def test_csrf_is_required_and_valid_staff_form_token_succeeds(self):
        client = Client(enforce_csrf_checks=True)
        self.login(client, self.staff)
        self.assertEqual(client.post(self.url, {"requires_approval": "0"}).status_code, 403)
        form_page = client.get(reverse("staff-rooms"))
        token = form_page.context["csrf_token"]
        response = client.post(self.url, {"requires_approval": "0", "csrfmiddlewaretoken": str(token)})
        self.assertEqual(response.status_code, 302)
        self.room.refresh_from_db()
        self.assertFalse(self.room.requires_approval)

    def test_get_does_not_change_room(self):
        self.assertEqual(self.client.get(self.url, {"requires_approval": "0"}).status_code, 405)
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)

    def test_malformed_and_missing_boolean_actions_do_not_change_room(self):
        for values in (
            {},
            {"requires_approval": "false"},
            {"requires_approval": "yes"},
            {"requires_approval": ["1", "0"]},
            {"requires_approval": ["0", "0"]},
            {"requires_approval": ["0", "1", "1"]},
        ):
            with self.subTest(values=values):
                self.assertEqual(self.client.post(self.url, values).status_code, 400)
        self.room.refresh_from_db()
        self.assertTrue(self.room.requires_approval)
        self.assertFalse(AuditEvent.objects.filter(action="room_approval_changed").exists())

    def test_return_page_validation_prevents_open_redirect(self):
        for page in ("https://example.invalid/", "//example.invalid/", "-1", "0", "9999999", ["1", "2"]):
            with self.subTest(page=page):
                response = self.client.post(self.url, {"requires_approval": "0", "page": page})
                self.assertEqual(response.status_code, 400)
        response = self.client.post(self.url, {"requires_approval": "0", "next": "https://example.invalid/"})
        self.assertEqual(response.url, reverse("staff-rooms"))

    def test_staff_can_configure_inactive_room(self):
        self.room.is_active = False
        self.room.save(update_fields=["is_active"])
        self.assertEqual(self.client.post(self.url, {"requires_approval": "0"}).status_code, 302)
        self.room.refresh_from_db()
        self.assertFalse(self.room.requires_approval)
        self.assertFalse(self.room.is_active)

    def test_toggle_does_not_approve_or_modify_existing_pending_request(self):
        start = timezone.now() + timedelta(days=1)
        booking = Reservation.objects.create(
            room=self.room,
            organizer=self.employee,
            created_by=self.employee,
            kind="booking",
            status="pending",
            starts_at=start,
            ends_at=start + timedelta(hours=1),
            occupied_from=start,
            occupied_until=start + timedelta(hours=1),
            title="Existing request",
        )
        old_revision = booking.revision
        self.client.post(self.url, {"requires_approval": "0"})
        booking.refresh_from_db()
        self.assertEqual(booking.status, Reservation.Status.PENDING)
        self.assertEqual(booking.revision, old_revision)
        self.assertIsNone(booking.approved_at)
        self.assertIsNone(booking.approved_by)

    def test_unknown_room_returns_404_without_audit(self):
        response = self.client.post(reverse("staff-room-approval", args=[999999]), {"requires_approval": "0"})
        self.assertEqual(response.status_code, 404)
        self.assertFalse(AuditEvent.objects.filter(action="room_approval_changed").exists())
