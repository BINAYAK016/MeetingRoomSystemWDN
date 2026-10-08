from datetime import date, datetime, timedelta
from unittest.mock import patch
from zoneinfo import ZoneInfo

from django import forms
from django.db import IntegrityError, connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import Client, TestCase, TransactionTestCase, override_settings
from django.urls import reverse

from booking.forms import BookingForm
from booking.models import AuditEvent, BookingPolicy, Department, Notification, Reservation, Room, User
from booking.services.auth_security import staff_session_verified

LOCAL_TZ = ZoneInfo("Asia/Kathmandu")
NOW = datetime(2026, 10, 8, 8, tzinfo=LOCAL_TZ)
DAY = date(2026, 10, 9)
DEFAULT_DEPARTMENTS = {
    "Accounts",
    "Administrative",
    "Logistics",
    "Sales",
    "Oracle Support",
    "Dell Support",
    "Toshiba",
    "ATM support",
}


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
class DepartmentBookingTests(TestCase):
    def setUp(self):
        clock = patch("django.utils.timezone.now", return_value=NOW)
        clock.start()
        self.addCleanup(clock.stop)
        BookingPolicy.objects.get_or_create(pk=1)
        self.employee = User.objects.create_user("person@wdn.com.np", department="Accounts")
        self.other = User.objects.create_user("other@transgate.com.np")
        self.room = Room.objects.create(name="Planning room", location="WDN", floor="2", capacity=8)
        self.client.force_login(self.employee)

    def values(self, **changes):
        data = {
            "room": self.room.pk,
            "date": DAY.isoformat(),
            "start_time": "11:00",
            "end_time": "12:00",
            "title": "Department planning",
            "meeting_type": "internal",
            "department": "Accounts",
            "external_attendee_count": "0",
            "attendees": "",
            "recurrence": "none",
        }
        data.update(changes)
        return data

    def choices(self, response):
        return dict(response.context["form"].fields["department"].choices)

    def existing_booking(self, department="Legacy Operations"):
        starts = datetime(2026, 10, 9, 11, tzinfo=LOCAL_TZ)
        return Reservation.objects.create(
            room=self.room,
            organizer=self.employee,
            created_by=self.employee,
            kind="booking",
            status="pending",
            title="Existing planning",
            department=department,
            starts_at=starts,
            ends_at=starts + timedelta(hours=1),
            occupied_from=starts,
            occupied_until=starts + timedelta(hours=1, minutes=15),
        )

    def test_requested_departments_and_placeholder_render_as_dropdown(self):
        response = self.client.get(reverse("booking-new"))
        field = response.context["form"].fields["department"]
        self.assertIsInstance(field, forms.ChoiceField)
        self.assertIsInstance(field.widget, forms.Select)
        self.assertTrue(DEFAULT_DEPARTMENTS.issubset(self.choices(response)))
        self.assertIn("", self.choices(response))
        self.assertContains(response, 'name="department"')
        self.assertContains(response, '<option value="Oracle Support"')

    def test_active_profile_department_is_prefilled_for_new_booking(self):
        response = self.client.get(reverse("booking-new"))
        self.assertEqual(response.context["form"]["department"].value(), "Accounts")
        self.assertContains(response, '<option value="Accounts" selected>')

    def test_staff_added_active_department_is_available_without_restarting(self):
        Department.objects.create(name="Engineering")
        self.assertIn("Engineering", self.choices(self.client.get(reverse("booking-new"))))
        response = self.client.post(reverse("booking-new"), self.values(department="Engineering"))
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Reservation.objects.get(kind="booking").department, "Engineering")

    def test_booking_stores_selected_name_as_historical_string_snapshot(self):
        response = self.client.post(reverse("booking-new"), self.values(department="Sales"))
        self.assertEqual(response.status_code, 302)
        booking = Reservation.objects.get(kind="booking")
        Department.objects.filter(name="Sales").update(name="Business Development", is_active=False)
        booking.refresh_from_db()
        self.assertEqual(booking.department, "Sales")
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Accounts")

    def test_unknown_and_inactive_departments_are_rejected_without_booking_or_notifications(self):
        Department.objects.create(name="Retired division", is_active=False)
        for name in ("Invented division", "Retired division", "x" * 121):
            with self.subTest(name=name):
                response = self.client.post(reverse("booking-new"), self.values(department=name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("department", response.context["form"].errors)
        self.assertFalse(Reservation.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertFalse(AuditEvent.objects.filter(action="booking_created").exists())

    def test_deactivated_profile_department_is_not_an_option_for_new_bookings(self):
        Department.objects.filter(name="Accounts").update(is_active=False)
        response = self.client.get(reverse("booking-new"))
        self.assertNotIn("Accounts", self.choices(response))
        self.assertIn(response.context["form"]["department"].value(), (None, ""))
        self.assertEqual(
            self.client.post(reverse("booking-new"), self.values(department="Accounts")).status_code,
            200,
        )
        self.assertFalse(Reservation.objects.exists())

    def test_profile_uses_active_dropdown_and_changes_prefill(self):
        response = self.client.get(reverse("profile"))
        self.assertIsInstance(response.context["form"].fields["department"].widget, forms.Select)
        self.assertTrue(DEFAULT_DEPARTMENTS.issubset(self.choices(response)))
        response = self.client.post(
            reverse("profile"), {"first_name": "Office", "last_name": "User", "department": "Dell Support"}
        )
        self.assertRedirects(response, reverse("profile"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Dell Support")
        self.assertEqual(
            self.client.get(reverse("booking-new")).context["form"]["department"].value(), "Dell Support"
        )

    def test_profile_rejects_unknown_names_and_other_users_inactive_departments(self):
        Department.objects.create(name="Closed department", is_active=False)
        User.objects.filter(pk=self.other.pk).update(department="Closed department")
        for name in ("Made up department", "Closed department"):
            response = self.client.post(reverse("profile"), {"department": name})
            self.assertEqual(response.status_code, 200)
            self.assertIn("department", response.context["form"].errors)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Accounts")
        self.assertFalse(AuditEvent.objects.filter(action="profile_updated").exists())

    def test_profile_can_keep_own_inactive_department_without_reintroducing_it_for_new_bookings(self):
        Department.objects.filter(name="Accounts").update(is_active=False)
        response = self.client.get(reverse("profile"))
        self.assertIn("Accounts", self.choices(response))
        self.assertEqual(response.context["form"]["department"].value(), "Accounts")
        response = self.client.post(reverse("profile"), {"first_name": "Changed", "department": "Accounts"})
        self.assertRedirects(response, reverse("profile"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.first_name, "Changed")
        self.assertEqual(self.employee.department, "Accounts")
        self.assertNotIn("Accounts", self.choices(self.client.get(reverse("booking-new"))))

    def test_profile_can_keep_own_unlisted_legacy_name_or_switch_to_an_active_department(self):
        User.objects.filter(pk=self.employee.pk).update(department="Historic Services")
        response = self.client.get(reverse("profile"))
        self.assertIn("Historic Services", self.choices(response))
        response = self.client.post(
            reverse("profile"), {"first_name": "Changed", "department": "Historic Services"}
        )
        self.assertRedirects(response, reverse("profile"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Historic Services")
        self.assertNotIn("Historic Services", self.choices(self.client.get(reverse("booking-new"))))
        self.assertRedirects(
            self.client.post(reverse("profile"), {"department": "Logistics"}), reverse("profile")
        )
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Logistics")

    def test_own_booking_edit_can_preserve_legacy_name_without_changing_catalog(self):
        booking = self.existing_booking()
        url = reverse("booking-edit", args=[booking.pk])
        response = self.client.get(url)
        self.assertIn(booking.department, self.choices(response))
        response = self.client.post(url, self.values(department=booking.department, title="Updated planning"))
        self.assertEqual(response.status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.department, "Legacy Operations")
        self.assertEqual(booking.title, "Updated planning")
        self.assertFalse(Department.objects.filter(name="Legacy Operations").exists())
        self.assertNotIn("Legacy Operations", self.choices(self.client.get(reverse("booking-new"))))

    def test_own_booking_edit_can_keep_inactive_department_or_choose_active_name(self):
        booking = self.existing_booking(department="Accounts")
        Department.objects.filter(name="Accounts").update(is_active=False)
        url = reverse("booking-edit", args=[booking.pk])
        self.assertIn("Accounts", self.choices(self.client.get(url)))
        self.assertEqual(self.client.post(url, self.values(title="Preserved inactive")).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.department, "Accounts")
        self.assertEqual(self.client.post(url, self.values(department="Sales")).status_code, 302)
        booking.refresh_from_db()
        self.assertEqual(booking.department, "Sales")

    def test_legacy_edit_exception_only_allows_saved_department(self):
        booking = self.existing_booking()
        Department.objects.create(name="Another retired department", is_active=False)
        response = self.client.post(
            reverse("booking-edit", args=[booking.pk]), self.values(department="Another retired department")
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("department", response.context["form"].errors)
        booking.refresh_from_db()
        self.assertEqual(booking.department, "Legacy Operations")
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(reverse("booking-edit", args=[booking.pk])).status_code, 404)
        response = self.client.post(reverse("booking-new"), self.values(department="Legacy Operations"))
        self.assertEqual(response.status_code, 200)
        self.assertIn("department", response.context["form"].errors)

    def test_form_revalidates_current_active_choices_after_page_was_opened(self):
        self.client.get(reverse("booking-new"))
        Department.objects.filter(name="Accounts").update(is_active=False)
        form = BookingForm(self.values())
        self.assertFalse(form.is_valid())
        self.assertIn("department", form.errors)


class DepartmentManagementTests(TestCase):
    def setUp(self):
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.employee = User.objects.create_user("employee@wdn.com.np", department="Accounts")
        self.department = Department.objects.get(name="Accounts")
        self.login(self.client, self.staff)
        self.list_url = reverse("staff-departments")
        self.new_url = reverse("staff-department-new")
        self.edit_url = reverse("staff-department-edit", args=[self.department.pk])

    def login(self, client, user, *, verified=True, version=None):
        client.force_login(user)
        session = client.session
        session["staff_verified"] = verified
        session["staff_auth_version"] = user.auth_version if version is None else version
        session.save()

    def values(self, **changes):
        values = {"name": "Business Development", "is_active": "on"}
        values.update(changes)
        return values

    def test_departments_navigation_list_and_editor_are_available_to_verified_staff(self):
        response = self.client.get(self.list_url)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Departments")
        self.assertContains(response, self.new_url)
        self.assertContains(response, self.edit_url)
        self.assertContains(response, self.department.name)
        form = self.client.get(self.new_url)
        self.assertContains(form, 'name="csrfmiddlewaretoken"')
        self.assertIn("is_active", form.context["form"].fields)
        self.assertContains(self.client.get(reverse("staff-rooms")), self.list_url)

    def test_department_creation_is_trimmed_available_to_employees_and_audited(self):
        response = self.client.post(self.new_url, self.values(name="  Business Development  "))
        self.assertRedirects(response, self.list_url)
        created = Department.objects.get(name="Business Development")
        self.assertTrue(created.is_active)
        event = AuditEvent.objects.get(action="department_created")
        self.assertEqual(event.actor, self.staff)
        self.assertEqual(event.target_type, "department")
        self.assertEqual(event.target_id, created.pk)
        self.assertEqual(event.outcome, "success")
        self.assertEqual(event.details, {"previous": None, "name": created.name, "active": True})
        self.client.force_login(self.employee)
        choices = dict(self.client.get(reverse("booking-new")).context["form"].fields["department"].choices)
        self.assertIn(created.name, choices)

    def test_rename_deactivate_and_reactivate_are_audited_and_keep_existing_strings(self):
        response = self.client.post(self.edit_url, self.values(name="Financial Accounts"))
        self.assertRedirects(response, self.list_url)
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Financial Accounts")
        event = AuditEvent.objects.get(action="department_modified")
        self.assertEqual(
            event.details,
            {"previous": {"name": "Accounts", "active": True}, "name": "Financial Accounts", "active": True},
        )
        self.client.post(self.edit_url, self.values(name="Financial Accounts", is_active=""))
        self.department.refresh_from_db()
        self.assertFalse(self.department.is_active)
        self.client.post(self.edit_url, self.values(name="Financial Accounts"))
        self.department.refresh_from_db()
        self.assertTrue(self.department.is_active)
        self.assertEqual(AuditEvent.objects.filter(action="department_modified").count(), 3)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Accounts")

    def test_duplicate_names_including_inactive_and_case_variants_are_rejected(self):
        Department.objects.create(name="Legacy services", is_active=False)
        count = Department.objects.count()
        for name in ("accounts", " ACCOUNTS ", "LEGACY SERVICES"):
            with self.subTest(name=name):
                response = self.client.post(self.new_url, self.values(name=name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("name", response.context["form"].errors)
        self.assertEqual(Department.objects.count(), count)
        self.assertFalse(AuditEvent.objects.filter(action="department_created").exists())
        response = self.client.post(self.edit_url, self.values(name="Sales"))
        self.assertIn("name", response.context["form"].errors)
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Accounts")

    def test_blank_and_overlong_names_are_rejected_without_mutating(self):
        count = Department.objects.count()
        for name in ("", "   ", "x" * 121):
            with self.subTest(name=name):
                response = self.client.post(self.new_url, self.values(name=name))
                self.assertEqual(response.status_code, 200)
                self.assertIn("name", response.context["form"].errors)
        self.assertEqual(Department.objects.count(), count)
        self.assertFalse(AuditEvent.objects.filter(action="department_created").exists())

    def test_database_uniqueness_also_rejects_case_insensitive_duplicates(self):
        with self.assertRaises(IntegrityError), transaction.atomic():
            Department.objects.create(name="ACCOUNTS")
        self.assertEqual(Department.objects.filter(name__iexact="accounts").count(), 1)

    def test_routes_deny_anonymous_employees_unverified_and_stale_staff(self):
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
            for url in (self.list_url, self.new_url, self.edit_url):
                with self.subTest(url=url, client=client):
                    response = client.get(url)
                    self.assertRedirects(response, reverse("staff-login"))
                    response = client.post(url, self.values())
                    self.assertRedirects(response, reverse("staff-login"))
        self.assertFalse(Department.objects.filter(name="Business Development").exists())
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Accounts")

    def test_deactivated_or_demoted_staff_cannot_modify_departments(self):
        for field in ("is_active", "is_staff"):
            user = User.objects.create_user(f"{field}@wdn.com.np", is_staff=True)
            client = Client()
            self.login(client, user)
            User.objects.filter(pk=user.pk).update(**{field: False})
            self.assertRedirects(client.post(self.new_url, self.values()), reverse("staff-login"))
            self.assertRedirects(client.post(self.edit_url, self.values()), reverse("staff-login"))
        self.assertFalse(AuditEvent.objects.filter(action__startswith="department_").exists())

    def test_revoked_staff_access_is_rechecked_under_lock_before_mutation(self):
        def revoke_after_initial_check(request):
            allowed = staff_session_verified(request)
            User.objects.filter(pk=self.staff.pk).update(is_staff=False)
            return allowed

        for url in (self.new_url, self.edit_url):
            User.objects.filter(pk=self.staff.pk).update(is_staff=True)
            with patch("booking.staff_views.staff_session_verified", side_effect=revoke_after_initial_check):
                response = self.client.post(url, self.values())
            self.assertRedirects(response, reverse("staff-login"))
        self.assertFalse(Department.objects.filter(name="Business Development").exists())
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Accounts")
        self.assertFalse(AuditEvent.objects.filter(action__startswith="department_").exists())

    def test_department_forms_require_csrf_and_accept_valid_form_token(self):
        client = Client(enforce_csrf_checks=True)
        self.login(client, self.staff)
        for url in (self.new_url, self.edit_url):
            self.assertEqual(client.post(url, self.values()).status_code, 403)
        page = client.get(self.new_url)
        data = {**self.values(), "csrfmiddlewaretoken": str(page.context["csrf_token"])}
        self.assertRedirects(client.post(self.new_url, data), self.list_url)
        self.assertTrue(Department.objects.filter(name="Business Development").exists())

    def test_missing_department_does_not_create_one_and_get_does_not_save(self):
        self.assertEqual(self.client.get(reverse("staff-department-edit", args=[999999])).status_code, 404)
        self.assertEqual(self.client.get(self.new_url, self.values()).status_code, 200)
        self.assertEqual(self.client.get(self.edit_url, self.values()).status_code, 200)
        self.assertFalse(Department.objects.filter(name="Business Development").exists())
        self.department.refresh_from_db()
        self.assertEqual(self.department.name, "Accounts")
        self.assertFalse(AuditEvent.objects.filter(action__startswith="department_").exists())

    def test_people_editor_uses_catalog_dropdown_and_can_assign_active_department(self):
        response = self.client.get(reverse("staff-users"))
        self.assertIsInstance(response.context["form"].fields["department"].widget, forms.Select)
        self.assertIn("Oracle Support", dict(response.context["form"].fields["department"].choices))
        response = self.client.post(
            reverse("staff-user-save"),
            {"email": self.employee.email, "department": "Oracle Support", "is_active": "on"},
        )
        self.assertRedirects(response, reverse("staff-users"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Oracle Support")
        self.assertTrue(self.employee.is_active)
        self.assertFalse(self.employee.is_staff)

    def test_people_editor_can_keep_existing_user_legacy_name_without_creating_catalog_entry(self):
        User.objects.filter(pk=self.employee.pk).update(department="Historic division")
        response = self.client.get(reverse("staff-users"), {"edit": self.employee.pk})
        self.assertIn("Historic division", dict(response.context["form"].fields["department"].choices))
        response = self.client.post(
            reverse("staff-user-save"),
            {
                "email": self.employee.email,
                "first_name": "Updated",
                "department": "Historic division",
                "is_active": "on",
            },
        )
        self.assertRedirects(response, reverse("staff-users"))
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Historic division")
        self.assertEqual(self.employee.first_name, "Updated")
        self.assertFalse(Department.objects.filter(name="Historic division").exists())

    def test_people_editor_rejects_unknown_or_another_users_legacy_name(self):
        User.objects.create_user("legacy@wdn.com.np", department="Private legacy division")
        for email in (self.employee.email, "new@wdn.com.np"):
            response = self.client.post(
                reverse("staff-user-save"),
                {"email": email, "department": "Private legacy division", "is_active": "on"},
            )
            self.assertEqual(response.status_code, 200)
            self.assertIn("department", response.context["form"].errors)
        self.employee.refresh_from_db()
        self.assertEqual(self.employee.department, "Accounts")
        self.assertFalse(User.objects.filter(email="new@wdn.com.np").exists())


class DepartmentMigrationTests(TransactionTestCase):
    migrate_from = [("booking", "0011_room_requires_approval")]
    migrate_to = [("booking", "0012_department")]

    def test_seeded_catalog_imports_legacy_names_without_rewriting_history(self):
        executor = MigrationExecutor(connection)
        latest_schema = executor.loader.graph.leaf_nodes()
        self.addCleanup(lambda: MigrationExecutor(connection).migrate(latest_schema))
        executor.migrate(self.migrate_from)
        old = executor.loader.project_state(self.migrate_from).apps
        users = old.get_model("booking", "User")
        user = users.objects.create(email="legacy@wdn.com.np", password="!", department="Legacy Services")
        users.objects.create(email="case@wdn.com.np", password="!", department="accounts")
        users.objects.create(email="empty@wdn.com.np", password="!", department="   ")
        room = old.get_model("booking", "Room").objects.create(
            name="Legacy room", location="WDN", floor="2", capacity=8
        )
        reservations = old.get_model("booking", "Reservation")
        starts = NOW + timedelta(days=1, hours=3)
        booking = reservations.objects.create(
            room_id=room.pk,
            organizer_id=user.pk,
            created_by_id=user.pk,
            kind="booking",
            status="cancelled",
            title="Historical planning",
            department="Archived Operations",
            starts_at=starts,
            ends_at=starts + timedelta(hours=1),
            occupied_from=starts,
            occupied_until=starts + timedelta(hours=1, minutes=15),
            revision=4,
        )
        before_users = list(users.objects.order_by("pk").values())
        before_bookings = list(reservations.objects.order_by("pk").values())
        executor = MigrationExecutor(connection)
        executor.migrate(self.migrate_to)
        current = executor.loader.project_state(self.migrate_to).apps
        departments = current.get_model("booking", "Department")
        self.assertTrue(
            DEFAULT_DEPARTMENTS.issubset(
                set(departments.objects.filter(is_active=True).values_list("name", flat=True))
            )
        )
        self.assertTrue(departments.objects.filter(name="Legacy Services", is_active=True).exists())
        self.assertTrue(departments.objects.filter(name="Archived Operations", is_active=True).exists())
        self.assertEqual(departments.objects.filter(name__iexact="accounts").count(), 1)
        self.assertFalse(departments.objects.filter(name="").exists())
        self.assertEqual(
            list(current.get_model("booking", "User").objects.order_by("pk").values()), before_users
        )
        self.assertEqual(
            list(current.get_model("booking", "Reservation").objects.order_by("pk").values()), before_bookings
        )
        self.assertEqual(current.get_model("booking", "Reservation").objects.get(pk=booking.pk).revision, 4)
