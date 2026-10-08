import io
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import skipUnless
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from PIL import Image, PngImagePlugin

from booking.models import Room, User
from booking.services.room_photos import PHOTO_NAME_PATTERN


class RoomPhotoTests(TestCase):
    def setUp(self):
        self.media = TemporaryDirectory()
        self.media_settings = override_settings(MEDIA_ROOT=self.media.name)
        self.media_settings.enable()
        self.addCleanup(self.media.cleanup)
        self.addCleanup(self.media_settings.disable)
        self.employee = User.objects.create_user("employee@wdn.com.np")
        self.staff = User.objects.create_user("desk@wdn.com.np", is_staff=True)
        self.client.force_login(self.staff)
        session = self.client.session
        session["staff_verified"] = True
        session["staff_auth_version"] = self.staff.auth_version
        session.save()

    def photo(self, format="PNG", size=(40, 24)):
        image = Image.new("RGB", size, "navy")
        output = io.BytesIO()
        if format == "PNG":
            metadata = PngImagePlugin.PngInfo()
            metadata.add_text("Comment", "private-camera-comment")
            image.save(output, format=format, pnginfo=metadata)
        else:
            exif = Image.Exif()
            exif[315] = "private-camera-owner"
            image.save(output, format=format, exif=exif)
        return SimpleUploadedFile("supplied-room-name.png", output.getvalue(), content_type="image/png")

    def data(self, **changes):
        values = {
            "name": "Actual office room",
            "location": "WDN",
            "floor": "2",
            "capacity": "8",
            "facilities_text": "Projector",
            "is_active": "on",
        }
        values.update(changes)
        return values

    def create(self, **changes):
        values = {"photo": self.photo(), **changes}
        response = self.client.post(reverse("staff-room-new"), self.data(**values))
        self.assertEqual(response.status_code, 302)
        return Room.objects.get()

    def image_response(self, client, room):
        response = client.get(reverse("room-photo", args=[room.pk]))
        if response.status_code == 200:
            # Client's streaming iterator closes the response while protecting
            # TestCase's transaction from request_finished connection cleanup.
            content = b"".join(response.streaming_content)
            return response, content
        return response, b""

    def test_staff_upload_is_sanitized_and_can_be_viewed_by_authenticated_employee(self):
        room = self.create()
        self.assertTrue(PHOTO_NAME_PATTERN.fullmatch(room.photo.name))
        self.assertNotIn("supplied-room-name", room.photo.name)
        stored = Path(room.photo.path).read_bytes()
        self.assertNotIn(b"private-camera-comment", stored)
        with Image.open(io.BytesIO(stored)) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertFalse(image.getexif())
        employee = Client()
        employee.force_login(self.employee)
        response, content = self.image_response(employee, room)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(content, stored)
        self.assertEqual(response["Content-Type"], "image/jpeg")
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn("no-store", response["Cache-Control"])
        self.assertIn(
            "multipart/form-data",
            self.client.get(reverse("staff-room-edit", args=[room.pk])).content.decode(),
        )
        self.assertEqual(Client().get(reverse("room-photo", args=[room.pk])).status_code, 302)

    def test_upload_preserves_room_when_photo_is_optional(self):
        response = self.client.post(reverse("staff-room-new"), self.data())
        self.assertEqual(response.status_code, 302)
        room = Room.objects.get()
        self.assertFalse(room.photo)
        self.assertEqual(self.client.get(reverse("room-photo", args=[room.pk])).status_code, 404)

    def test_employees_and_staff_without_second_factor_cannot_upload(self):
        for user in (self.employee, self.staff):
            client = Client()
            client.force_login(user)
            response = client.post(reverse("staff-room-new"), self.data(photo=self.photo()))
            self.assertEqual(response.status_code, 302)
            self.assertEqual(response.url, reverse("staff-login"))
        self.assertFalse(Room.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.jpg")))

    def test_inactive_photo_is_visible_only_to_verified_staff(self):
        room = self.create()
        room.is_active = False
        room.save(update_fields=["is_active"])
        employee = Client()
        employee.force_login(self.employee)
        self.assertEqual(employee.get(reverse("room-photo", args=[room.pk])).status_code, 404)
        unverified = Client()
        unverified.force_login(self.staff)
        self.assertEqual(unverified.get(reverse("room-photo", args=[room.pk])).status_code, 404)
        response, content = self.image_response(self.client, room)
        self.assertEqual(response.status_code, 200)
        self.assertTrue(content)

    def test_svg_and_corrupt_images_are_rejected_without_saving_room(self):
        for name, body in (
            ("unsafe.svg", b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>'),
            ("broken.jpg", b"not a readable JPEG"),
        ):
            response = self.client.post(
                reverse("staff-room-new"), self.data(photo=SimpleUploadedFile(name, body))
            )
            self.assertContains(response, "not a supported, readable room photo")
        self.assertFalse(Room.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.jpg")))

    def test_photo_byte_and_pixel_limits_are_enforced(self):
        too_large = SimpleUploadedFile("large.jpg", b"x" * (5 * 1024 * 1024 + 1))
        response = self.client.post(reverse("staff-room-new"), self.data(photo=too_large))
        self.assertContains(response, "smaller than 5 MB")
        response = self.client.post(reverse("staff-room-new"), self.data(photo=self.photo(size=(4001, 3000))))
        self.assertContains(response, "at most 12 million pixels")
        self.assertFalse(Room.objects.exists())

    def test_animated_png_is_rejected(self):
        output = io.BytesIO()
        first, second = Image.new("RGB", (8, 8), "navy"), Image.new("RGB", (8, 8), "red")
        first.save(output, format="PNG", save_all=True, append_images=[second], duration=100, loop=0)
        response = self.client.post(
            reverse("staff-room-new"), self.data(photo=SimpleUploadedFile("animated.png", output.getvalue()))
        )
        self.assertContains(response, "rather than an animated image")
        self.assertFalse(Room.objects.exists())

    def test_jpeg_metadata_is_removed_and_long_edge_is_bounded(self):
        room = self.create(photo=self.photo(format="JPEG", size=(2000, 1000)))
        stored = Path(room.photo.path).read_bytes()
        self.assertNotIn(b"private-camera-owner", stored)
        with Image.open(io.BytesIO(stored)) as image:
            self.assertEqual(image.size, (1920, 960))
            self.assertFalse(image.getexif())

    def test_photo_replacement_and_removal_delete_old_file_after_commit(self):
        room = self.create()
        old_path = Path(room.photo.path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("staff-room-edit", args=[room.pk]), self.data(photo=self.photo())
            )
        self.assertEqual(response.status_code, 302)
        room.refresh_from_db()
        self.assertNotEqual(room.photo.path, str(old_path))
        self.assertFalse(old_path.exists())
        current_path = Path(room.photo.path)
        response = self.client.post(reverse("staff-room-edit", args=[room.pk]), self.data())
        self.assertEqual(response.status_code, 302)
        room.refresh_from_db()
        self.assertEqual(Path(room.photo.path), current_path)
        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.post(
                reverse("staff-room-edit", args=[room.pk]), self.data(remove_photo="on")
            )
        self.assertEqual(response.status_code, 302)
        room.refresh_from_db()
        self.assertFalse(room.photo)
        self.assertFalse(current_path.exists())

    def test_photo_saved_before_database_failure_is_cleaned_up(self):
        with patch(
            "booking.staff_views.AuditEvent.objects.create", side_effect=IntegrityError("forced rollback")
        ):
            response = self.client.post(reverse("staff-room-new"), self.data(photo=self.photo()))
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Room.objects.exists())
        self.assertFalse(list(Path(self.media.name).rglob("*.jpg")))

    def test_storage_failure_preserves_existing_photo_and_room(self):
        room = self.create()
        old_name, old_path = room.photo.name, Path(room.photo.path)
        with patch.object(room.photo.storage, "save", side_effect=PermissionError("storage unavailable")):
            response = self.client.post(
                reverse("staff-room-edit", args=[room.pk]), self.data(name="Changed", photo=self.photo())
            )
        self.assertContains(response, "The photo could not be saved")
        room.refresh_from_db()
        self.assertEqual(room.name, "Actual office room")
        self.assertEqual(room.photo.name, old_name)
        self.assertTrue(old_path.exists())

    def test_conflicting_remove_and_upload_preserves_existing_photo(self):
        room = self.create()
        old_name = room.photo.name
        response = self.client.post(
            reverse("staff-room-edit", args=[room.pk]), self.data(photo=self.photo(), remove_photo="on")
        )
        self.assertContains(response, "Choose a new photo or remove the current one")
        room.refresh_from_db()
        self.assertEqual(room.photo.name, old_name)
        self.assertEqual(len(list(Path(self.media.name).rglob("*.jpg"))), 1)

    def test_arbitrary_media_path_is_not_served(self):
        room = Room.objects.create(name="Office", location="WDN", floor="2", capacity=8, photo="private.txt")
        Path(self.media.name, "private.txt").write_text("private-data", encoding="utf-8")
        response = self.client.get(reverse("room-photo", args=[room.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"private-data", response.content)

    @skipUnless(os.name != "nt", "Container deployment uses Linux path and symlink behavior")
    def test_symlink_escape_cannot_serve_arbitrary_file(self):
        room = Room.objects.create(
            name="Office", location="WDN", floor="2", capacity=8, photo="rooms/photos/" + "a" * 32 + ".jpg"
        )
        path = Path(self.media.name, room.photo.name)
        path.parent.mkdir(parents=True)
        secret = Path(self.media.name, "private.txt")
        secret.write_text("private-data", encoding="utf-8")
        path.symlink_to(secret)
        response = self.client.get(reverse("room-photo", args=[room.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertNotIn(b"private-data", response.content)
