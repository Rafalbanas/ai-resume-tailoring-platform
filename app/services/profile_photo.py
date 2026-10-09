import io
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError


class ProfilePhotoError(ValueError):
    pass


class ProfilePhotoStore:
    ALLOWED = {
        ".jpg": ("image/jpeg", "JPEG"),
        ".jpeg": ("image/jpeg", "JPEG"),
        ".png": ("image/png", "PNG"),
        ".webp": ("image/webp", "WEBP"),
    }

    def __init__(self, directory: Path, max_bytes: int = 5_000_000):
        self.directory = directory
        self.path = directory / "profile_photo.jpg"
        self.max_bytes = max_bytes

    def exists(self) -> bool:
        return self.path.is_file()

    def save(self, filename: str, content_type: str, content: bytes, crop_x: int = 50, crop_y: int = 50) -> Path:
        suffix = Path(filename).suffix.casefold()
        expected = self.ALLOWED.get(suffix)
        if not expected or content_type.casefold() != expected[0]:
            raise ProfilePhotoError("Upload a JPG, JPEG, PNG, or WEBP image.")
        if not content or len(content) > self.max_bytes:
            raise ProfilePhotoError(f"The profile photo must be smaller than {self.max_bytes // 1_000_000} MB.")
        try:
            with Image.open(io.BytesIO(content)) as source:
                source.verify()
            with Image.open(io.BytesIO(content)) as source:
                if source.format != expected[1]:
                    raise ProfilePhotoError("The file content does not match its extension and MIME type.")
                image = ImageOps.exif_transpose(source).convert("RGB")
                normalized = self._crop(image, crop_x, crop_y).resize((600, 600), Image.Resampling.LANCZOS)
        except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
            raise ProfilePhotoError("The uploaded file is not a valid supported image.") from exc

        self.directory.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".profile-photo-", suffix=".jpg", dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                normalized.save(handle, format="JPEG", quality=92, optimize=True)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self.path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return self.path

    @staticmethod
    def _crop(image: Image.Image, crop_x: int, crop_y: int) -> Image.Image:
        crop_x = max(0, min(100, crop_x)) / 100
        crop_y = max(0, min(100, crop_y)) / 100
        side = min(image.width, image.height)
        max_left = image.width - side
        max_top = image.height - side
        left = round(max_left * crop_x)
        top = round(max_top * crop_y)
        return image.crop((left, top, left + side, top + side))

    def remove(self) -> None:
        self.path.unlink(missing_ok=True)
