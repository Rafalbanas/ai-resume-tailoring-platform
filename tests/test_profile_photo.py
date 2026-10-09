import io
from pathlib import Path

import pytest
from docx import Document
from PIL import Image, features
from pypdf import PdfReader

from app.models.resume import TailoredResume
from app.services.docx_generator import generate_docx
from app.services.pdf_generator import PDFGenerator
from app.services.profile_photo import ProfilePhotoError, ProfilePhotoStore


def image_bytes(image_format: str, size: tuple[int, int] = (900, 600)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", size, (36, 77, 112)).save(output, format=image_format)
    return output.getvalue()


def heif_bytes(size: tuple[int, int] = (900, 600), format_name: str = "HEIF") -> bytes:
    import pillow_heif

    img = Image.new("RGB", size, (36, 77, 112))
    buf = io.BytesIO()
    heif_file = pillow_heif.from_pillow(img)
    heif_file.save(buf, format=format_name)
    return buf.getvalue()


@pytest.mark.parametrize(
    ("filename", "mime", "image_format"),
    [
        ("portrait.jpg", "image/jpeg", "JPEG"),
        ("portrait.png", "image/png", "PNG"),
        ("portrait.tif", "image/tiff", "TIFF"),
    ],
)
def test_upload_and_normalize_supported_photo(tmp_path, filename, mime, image_format):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    path = store.save(filename, mime, image_bytes(image_format), 25, 75)
    with Image.open(path) as normalized:
        assert normalized.size == (600, 600)
        assert normalized.format in ("JPEG", "WEBP")
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(not features.check("webp"), reason="Pillow was built without WEBP")
def test_upload_webp(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    assert store.save("portrait.webp", "image/webp", image_bytes("WEBP")).is_file()


def test_upload_heic_and_heif(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    heic_data = heif_bytes(size=(800, 600))
    path = store.save("IMG_1234.HEIC", "image/heic", heic_data)
    assert path.is_file()
    with Image.open(path) as normalized:
        assert normalized.size == (600, 600)
        assert normalized.format in ("JPEG", "WEBP")

    heif_data = heif_bytes(size=(600, 800), format_name="HEIF")
    path_heif = store.save("photo.heif", "image/heif", heif_data)
    assert path_heif.is_file()


def test_upload_rotated_exif_image(tmp_path):
    # Orientation 6: 90 deg CW rotation in EXIF
    img = Image.new("RGB", (800, 400), (50, 100, 150))
    exif = img.getexif()
    exif[0x0112] = 6  # EXIF orientation tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    store = ProfilePhotoStore(tmp_path / "profile_photo")
    path = store.save("rotated.jpg", "image/jpeg", buf.getvalue())
    with Image.open(path) as normalized:
        assert normalized.size == (600, 600)


def test_heic_to_preview_render(profile, resume_payload, tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    store.save("avatar.heic", "image/heic", heif_bytes())
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path, store)
    resume = TailoredResume.model_validate(resume_payload)
    html = generator.render_html(resume, profile, photo_enabled=True)
    assert "data:image/" in html
    assert "Profile photo" in html


def test_rejects_corrupted_heic_and_renamed_file(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    with pytest.raises(ProfilePhotoError, match="HEIC/HEIF"):
        store.save("fake.heic", "image/heic", b"This is not a HEIC file at all")
    with pytest.raises(ProfilePhotoError, match="HEIC/HEIF"):
        store.save("corrupted.heic", "image/heic", b"ftypheic\x00\x00\x00\x00corrupted-bytes")


def test_photo_persists_across_store_reload_and_replacement(tmp_path):
    directory = tmp_path / "profile_photo"
    store = ProfilePhotoStore(directory)
    store.save("first.png", "image/png", image_bytes("PNG"))
    first = store.path.read_bytes()

    reloaded = ProfilePhotoStore(directory)
    assert reloaded.exists()
    replacement = io.BytesIO()
    Image.new("RGB", (600, 900), (170, 50, 40)).save(replacement, format="JPEG")
    reloaded.save("replacement.jpg", "image/jpeg", replacement.getvalue())

    assert reloaded.path == store.path
    assert reloaded.path.read_bytes() != first
    assert set(p.name for p in directory.iterdir()) == {"current.webp", "current.jpg"}


def test_rejects_invalid_type(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    with pytest.raises(ProfilePhotoError, match="JPG"):
        store.save("portrait.gif", "image/gif", b"GIF89a")
    with pytest.raises(ProfilePhotoError, match="JPG"):
        store.save("portrait.pdf", "application/pdf", b"%PDF-1.4 dummy")
    with pytest.raises(ProfilePhotoError, match="Could not read this image"):
        store.save("portrait.jpg", "image/jpeg", b"not-an-image-content")


def test_rejects_oversized_photo(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo", max_bytes=20)
    with pytest.raises(ProfilePhotoError, match="smaller"):
        store.save("portrait.jpg", "image/jpeg", image_bytes("JPEG"))


def test_missing_photo_uses_initials_placeholder(profile, resume_payload, tmp_path):
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    html = generator.render_html(TailoredResume.model_validate(resume_payload), profile, photo_enabled=True)
    assert '<span>JT</span>' in html
    assert "Profile photo" not in html


def test_photo_on_off_and_ats_default(profile, resume_payload, tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    store.save("portrait.png", "image/png", image_bytes("PNG"))
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path, store)
    resume = TailoredResume.model_validate(resume_payload)
    enabled = generator.render_html(resume, profile, photo_enabled=True)
    disabled = generator.render_html(resume, profile, photo_enabled=False)
    ats = generator.render_html(resume, profile, template_name="ats_classic")
    assert "data:image/" in enabled
    assert "data:image/" not in disabled
    assert "<span>JT</span>" in disabled
    assert '<div class="portrait">' not in ats
    assert "ats-classic" in ats


def test_preview_avatar_is_interactive_but_export_markup_is_not(profile, resume_payload, tmp_path):
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    resume = TailoredResume.model_validate(resume_payload)
    preview = generator.render_html(resume, profile, interactive_photo=True)
    export = generator.render_html(resume, profile)

    assert 'id="quick-photo-avatar"' in preview
    assert 'title="Change profile photo"' in preview
    assert 'id="quick-photo-avatar"' not in export


def test_pdf_and_docx_generate_with_photo(profile, resume_payload, tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    store.save("portrait.jpg", "image/jpeg", image_bytes("JPEG"))
    resume = TailoredResume.model_validate(resume_payload)
    pdf_path = tmp_path / "resume-photo.pdf"
    docx_path = tmp_path / "resume-photo.docx"
    PDFGenerator(Path("templates"), Path("static"), tmp_path, store).generate(
        resume, profile, pdf_path, photo_enabled=True
    )
    generate_docx(resume, profile, docx_path, photo_path=store.path, photo_enabled=True)
    assert len(PdfReader(pdf_path).pages) == 1
    assert len(Document(docx_path).inline_shapes) == 1


def test_profile_photo_directory_is_gitignored():
    ignore = Path(".gitignore").read_text(encoding="utf-8")
    assert "data/profile_photo/" in ignore
