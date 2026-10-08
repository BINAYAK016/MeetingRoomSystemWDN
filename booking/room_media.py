from pathlib import Path

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from booking.models import Room
from booking.services.auth_security import staff_session_verified
from booking.services.room_photos import PHOTO_NAME_PATTERN


@never_cache
@login_required(login_url="sign-in")
@require_GET
def room_photo(request, room_id):
    rooms = Room.objects.all() if staff_session_verified(request) else Room.objects.filter(is_active=True)
    room = get_object_or_404(rooms, pk=room_id)
    if not room.photo or PHOTO_NAME_PATTERN.fullmatch(room.photo.name) is None:
        raise Http404
    try:
        photo_root = Path(settings.MEDIA_ROOT).resolve() / "rooms" / "photos"
        path = Path(room.photo.path).resolve(strict=True)
        path.relative_to(photo_root)
        if not path.is_file():
            raise Http404
        handle = path.open("rb")
    except (OSError, ValueError) as exc:
        raise Http404 from exc
    response = FileResponse(handle, content_type="image/jpeg")
    response["Content-Disposition"] = f'inline; filename="room-{room.pk}.jpg"'
    response["X-Content-Type-Options"] = "nosniff"
    response["Content-Security-Policy"] = "default-src 'none'; sandbox"
    return response
