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


@pytest.mark.parametrize(
    ("filename", "mime", "image_format"),
    [("portrait.jpg", "image/jpeg", "JPEG"), ("portrait.png", "image/png", "PNG")],
)
def test_upload_and_normalize_supported_photo(tmp_path, filename, mime, image_format):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    path = store.save(filename, mime, image_bytes(image_format), 25, 75)
    with Image.open(path) as normalized:
        assert normalized.size == (600, 600)
        assert normalized.format == "JPEG"
    assert path.stat().st_mode & 0o777 == 0o600


@pytest.mark.skipif(not features.check("webp"), reason="Pillow was built without WEBP")
def test_upload_webp(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    assert store.save("portrait.webp", "image/webp", image_bytes("WEBP")).is_file()


def test_rejects_invalid_type_and_mismatched_content(tmp_path):
    store = ProfilePhotoStore(tmp_path / "profile_photo")
    with pytest.raises(ProfilePhotoError, match="JPG"):
        store.save("portrait.gif", "image/gif", b"GIF89a")
    with pytest.raises(ProfilePhotoError, match="does not match"):
        store.save("portrait.jpg", "image/jpeg", image_bytes("PNG"))


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
    assert "data:image/jpeg;base64" in enabled
    assert "data:image/jpeg;base64" not in disabled
    assert "<span>JT</span>" in disabled
    assert '<div class="portrait">' not in ats
    assert "ats-classic" in ats


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
