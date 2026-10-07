import re
from datetime import timedelta
from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from booking.forms import BookingForm
from booking.models import EmailToken, Notification, Reservation, Room, User
from booking.services.bookings import BookingError, create_booking

OUTSIDE_EMPLOYEE_ADDRESSES = (
    "person@example.com",
    "person@wdn.net.np",
    "person@sub.transgate.com.np",
    "person@transgate.com.np.example.com",
    "person@transgatecom.np",
    "person@sub.wdn.com.np",
    "person@wdn.com.np.example.com",
)


@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend", EMAIL_READY=True)
class EmployeeDomainTests(TestCase):
    def setUp(self):
        self.room = Room.objects.create(name="Shared room", location="WDN", floor="2", capacity=8)
        self.day = timezone.localdate() + timedelta(days=1)
        while self.day.weekday() >= 5:
            self.day += timedelta(days=1)

    def booking_data(self, **changes):
        data = {
            "room": self.room.pk,
            "date": self.day.isoformat(),
            "start_time": "11:00",
            "end_time": "12:00",
            "title": "Joint planning",
            "meeting_type": "internal",
            "external_attendee_count": "0",
            "attendees": "WDN.COLLEAGUE@WDN.COM.NP, TRANS.COLLEAGUE@TRANSGATE.COM.NP",
            "recurrence": "none",
        }
        data.update(changes)
        return data

    def test_both_company_domains_complete_verified_employee_sign_in(self):
        for domain in ("wdn.com.np", "transgate.com.np"):
            with self.subTest(domain=domain):
                email = f"employee@{domain}"
                response = self.client.post(reverse("sign-in"), {"email": email.upper()})
                self.assertEqual(response.status_code, 200)
                self.assertEqual(mail.outbox[-1].to, [email])
                self.assertFalse(User.objects.filter(email=email).exists())
                link = re.search(r"https?://\S+/sign-in/link/\S+", mail.outbox[-1].body).group()
                self.assertRedirects(self.client.get(link), reverse("login-confirm"))
                self.assertEqual(self.client.post(reverse("login-confirm")).status_code, 302)
                user = User.objects.get(email=email)
                self.assertEqual(self.client.session["_auth_user_id"], str(user.pk))
                self.assertFalse(user.is_staff)
                self.assertFalse(user.is_superuser)
                self.assertFalse(user.has_usable_password())
                self.assertFalse(self.client.session["staff_verified"])
                self.assertRedirects(self.client.get(reverse("staff-dashboard")), reverse("staff-login"))
                self.client.post(reverse("sign-out"))

    def test_outsiders_and_similar_domains_do_not_receive_employee_links(self):
        for email in OUTSIDE_EMPLOYEE_ADDRESSES:
            with self.subTest(email=email):
                response = self.client.post(reverse("sign-in"), {"email": email})
                self.assertContains(response, "If the address is eligible and delivery is available")
        self.assertEqual(len(mail.outbox), 0)
        self.assertFalse(EmailToken.objects.exists())
        self.assertFalse(User.objects.exists())

    def test_transgate_employee_can_book_with_attendees_from_both_companies(self):
        employee = User.objects.create_user("organizer@transgate.com.np")
        self.client.force_login(employee)
        response = self.client.post(
            reverse("booking-new"),
            self.booking_data(
                attendees="WDN.COLLEAGUE@WDN.COM.NP; TRANS.COLLEAGUE@TRANSGATE.COM.NP\n"
                "trans.colleague@transgate.com.np"
            ),
        )
        self.assertEqual(response.status_code, 302)
        booking = Reservation.objects.get(kind="booking")
        self.assertEqual(booking.organizer, employee)
        self.assertSetEqual(
            set(booking.attendees.values_list("email", flat=True)),
            {"wdn.colleague@wdn.com.np", "trans.colleague@transgate.com.np"},
        )
        self.assertSetEqual(
            set(Notification.objects.filter(reservation=booking).values_list("recipient_email", flat=True)),
            {employee.email, "wdn.colleague@wdn.com.np", "trans.colleague@transgate.com.np"},
        )
        self.assertEqual(len(mail.outbox), 0)

    def test_staff_can_book_for_normalized_transgate_organizer(self):
        staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        form = BookingForm(self.booking_data(organizer_email="ORGANIZER@TRANSGATE.COM.NP"), staff=True)
        self.assertTrue(form.is_valid(), form.errors)
        booking = create_booking(form.cleaned_data, actor=staff, staff=True)[0]
        self.assertEqual(booking.organizer.email, "organizer@transgate.com.np")
        self.assertFalse(booking.organizer.is_staff)
        self.assertFalse(booking.organizer.has_usable_password())

    def test_outside_organizers_are_rejected_by_form_and_booking_service(self):
        staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        valid_form = BookingForm(self.booking_data(), staff=True)
        self.assertTrue(valid_form.is_valid(), valid_form.errors)
        for email in OUTSIDE_EMPLOYEE_ADDRESSES:
            with self.subTest(email=email):
                form = BookingForm(self.booking_data(organizer_email=email), staff=True)
                self.assertFalse(form.is_valid())
                self.assertIn("organizer_email", form.errors)
                with self.assertRaises(BookingError):
                    create_booking(
                        {**valid_form.cleaned_data, "organizer_email": email}, actor=staff, staff=True
                    )
        self.assertFalse(Reservation.objects.exists())
        self.assertFalse(Notification.objects.exists())
        self.assertEqual(User.objects.count(), 1)

    def test_staff_bootstrap_supports_normalized_transgate_address(self):
        call_command("create_staff_account", "DESK@TRANSGATE.COM.NP", stdout=StringIO())
        staff = User.objects.get(email="desk@transgate.com.np")
        self.assertTrue(staff.is_staff)
        self.assertTrue(staff.is_active)
        self.assertFalse(staff.is_superuser)
        self.assertFalse(staff.has_usable_password())
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [staff.email])
        self.assertIn("/staff/set-password/", mail.outbox[0].body)

    def test_staff_bootstrap_rejects_outside_domains_without_accounts_or_email(self):
        for email in OUTSIDE_EMPLOYEE_ADDRESSES:
            with self.subTest(email=email):
                with self.assertRaises(CommandError):
                    call_command("create_staff_account", email, stdout=StringIO())
        self.assertFalse(User.objects.exists())
        self.assertEqual(len(mail.outbox), 0)
