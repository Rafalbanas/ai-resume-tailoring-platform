import io
import logging
import os
import tempfile
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

try:
    import pillow_heif

    pillow_heif.register_heif_opener()
except Exception:  # pragma: no cover
    pass

logger = logging.getLogger(__name__)

# Protect against decompression bombs (max 40 megapixels)
Image.MAX_IMAGE_PIXELS = 40_000_000


class ProfilePhotoError(ValueError):
    pass


class ProfilePhotoStore:
    ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif", ".tif", ".tiff"}

    def __init__(self, directory: Path, max_bytes: int = 10_000_000):
        self.directory = directory
        self.webp_path = directory / "current.webp"
        self.jpg_path = directory / "current.jpg"
        self.legacy_path = directory / "profile_photo.jpg"
        self.max_bytes = max_bytes

    @property
    def path(self) -> Path:
        if self.webp_path.is_file():
            return self.webp_path
        if self.jpg_path.is_file():
            return self.jpg_path
        if self.legacy_path.is_file():
            return self.legacy_path
        return self.webp_path

    def exists(self) -> bool:
        return self.webp_path.is_file() or self.jpg_path.is_file() or self.legacy_path.is_file()

    def save(
        self,
        filename: str,
        content_type: str,
        content: bytes,
        crop_x: float = 50.0,
        crop_y: float = 50.0,
        crop_zoom: float = 1.0,
    ) -> Path:
        suffix = Path(filename).suffix.casefold() if filename else ""
        if not suffix and content_type:
            ct = content_type.lower()
            if "jpeg" in ct or "jpg" in ct:
                suffix = ".jpg"
            elif "png" in ct:
                suffix = ".png"
            elif "webp" in ct:
                suffix = ".webp"
            elif "heic" in ct or "heif" in ct:
                suffix = ".heic"
            elif "tiff" in ct or "tif" in ct:
                suffix = ".tif"
        if suffix and suffix not in self.ALLOWED_EXTENSIONS:
            raise ProfilePhotoError("Upload a JPG, JPEG, PNG, WEBP, or HEIC image.")
        if not content or len(content) > self.max_bytes:
            raise ProfilePhotoError(f"The profile photo must be smaller than {self.max_bytes // 1_000_000} MB.")

        try:
            with Image.open(io.BytesIO(content)) as source:
                source.verify()
        except Exception as exc:
            logger.warning("Profile photo verification failed: %s", exc)
            if suffix in {".heic", ".heif"} or "heic" in content_type.lower() or "heif" in content_type.lower():
                raise ProfilePhotoError("HEIC/HEIF image conversion failed.") from exc
            raise ProfilePhotoError("Could not read this image.") from exc

        try:
            with Image.open(io.BytesIO(content)) as source:
                if source.width > 10000 or source.height > 10000 or (source.width * source.height > 40_000_000):
                    raise ProfilePhotoError("The image is too large to process safely.")
                image = ImageOps.exif_transpose(source)
                image = image.convert("RGB")
                normalized = self._crop(image, crop_x, crop_y, crop_zoom).resize(
                    (600, 600), Image.Resampling.LANCZOS
                )
        except ProfilePhotoError:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            logger.warning("Profile photo processing failed: %s", exc)
            if suffix in {".heic", ".heif"} or "heic" in content_type.lower() or "heif" in content_type.lower():
                raise ProfilePhotoError("HEIC/HEIF image conversion failed.") from exc
            raise ProfilePhotoError("Could not read this image.") from exc
        except Image.DecompressionBombError as exc:
            raise ProfilePhotoError("The image is too large to process safely.") from exc

        self.directory.mkdir(parents=True, exist_ok=True)
        self._atomic_save(normalized, self.webp_path, "WEBP", quality=90)
        self._atomic_save(normalized, self.jpg_path, "JPEG", quality=92, optimize=True)
        if self.legacy_path.is_file():
            self.legacy_path.unlink(missing_ok=True)

        return self.path

    def _atomic_save(self, image: Image.Image, target: Path, fmt: str, **kwargs) -> None:
        fd, temporary = tempfile.mkstemp(prefix=f".{target.stem}-", suffix=target.suffix, dir=self.directory)
        try:
            with os.fdopen(fd, "wb") as handle:
                image.save(handle, format=fmt, **kwargs)
            os.chmod(temporary, 0o600)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    @staticmethod
    def _crop(image: Image.Image, crop_x: float, crop_y: float, crop_zoom: float = 1.0) -> Image.Image:
        crop_x = max(0.0, min(100.0, float(crop_x))) / 100.0
        crop_y = max(0.0, min(100.0, float(crop_y))) / 100.0
        crop_zoom = max(1.0, min(5.0, float(crop_zoom)))
        base_side = min(image.width, image.height)
        crop_side = base_side / crop_zoom
        max_left = image.width - crop_side
        max_top = image.height - crop_side
        left = round(max_left * crop_x)
        top = round(max_top * crop_y)
        right = round(left + crop_side)
        bottom = round(top + crop_side)
        return image.crop((left, top, right, bottom))

    def remove(self) -> None:
        self.webp_path.unlink(missing_ok=True)
        self.jpg_path.unlink(missing_ok=True)
        self.legacy_path.unlink(missing_ok=True)
