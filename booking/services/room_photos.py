import io
import logging
import re
import uuid
import warnings

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

MAX_PHOTO_BYTES = 5 * 1024 * 1024
MAX_PHOTO_PIXELS = 12_000_000
PHOTO_NAME_PATTERN = re.compile(r"rooms/photos/[a-f0-9]{32}(?:_[A-Za-z0-9]{7})?\.jpg\Z")
logger = logging.getLogger(__name__)


def normalize_room_photo(upload):
    if upload.size > MAX_PHOTO_BYTES:
        raise ValidationError("Choose a room photo smaller than 5 MB.")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            upload.seek(0)
            with Image.open(upload) as image:
                if image.format not in {"JPEG", "PNG", "WEBP"}:
                    raise ValidationError("Use a JPEG, PNG or WebP room photo.")
                if image.width * image.height > MAX_PHOTO_PIXELS:
                    raise ValidationError("Choose a room photo with at most 12 million pixels.")
                if getattr(image, "n_frames", 1) != 1:
                    raise ValidationError("Use a still room photo rather than an animated image.")
                image.verify()
            upload.seek(0)
            with Image.open(upload) as image:
                image = ImageOps.exif_transpose(image)
                image.thumbnail((1920, 1920), Image.Resampling.LANCZOS)
                if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
                    rgba = image.convert("RGBA")
                    normalized = Image.new("RGB", rgba.size, "white")
                    normalized.paste(rgba, mask=rgba.getchannel("A"))
                else:
                    normalized = image.convert("RGB")
                output = io.BytesIO()
                # Saving pixels only discards supplied names, metadata and appended content.
                normalized.save(output, format="JPEG", quality=85, optimize=True)
                return ContentFile(output.getvalue(), name=f"{uuid.uuid4().hex}.jpg")
    except (
        UnidentifiedImageError,
        OSError,
        SyntaxError,
        ValueError,
        Image.DecompressionBombError,
        Image.DecompressionBombWarning,
    ) as exc:
        raise ValidationError("This file is not a supported, readable room photo.") from exc


def delete_room_photo(storage, name):
    if not name or PHOTO_NAME_PATTERN.fullmatch(name) is None:
        return
    try:
        storage.delete(name)
    except OSError as exc:
        logger.warning("Unused room photo could not be removed (%s)", type(exc).__name__)
