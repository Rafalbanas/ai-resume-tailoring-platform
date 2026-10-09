import io
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image, features

import app.routes.web as web_routes
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume
from app.services.docx_generator import generate_docx
from app.services.pdf_generator import PDFGenerator
from app.services.profile_photo import ProfilePhotoStore
from app.services.storage import Storage


class NoopLimiter:
    def check(self, _key: str) -> None:
        return None


def image_bytes(image_format: str, color=(30, 80, 120)) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (700, 500), color).save(output, format=image_format)
    return output.getvalue()


@pytest.fixture
def quick_photo_app(tmp_path, profile, resume_payload, monkeypatch):
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "_validate_ajax_csrf", lambda _request: None)
    app = FastAPI()
    app.include_router(web_routes.router)
    storage = Storage(tmp_path / "data")
    store = ProfilePhotoStore(tmp_path / "data" / "profile_photo")
    app.state.settings = SimpleNamespace(profile_photo_max_bytes=5_000_000)
    app.state.limiter = NoopLimiter()
    app.state.profile = profile
    app.state.storage = storage
    app.state.profile_photo = store
    app.state.pdf_generator = PDFGenerator(Path("templates"), Path("static"), tmp_path / "data", store)
    app.state.docx_generator = generate_docx
    job = JobRequest(
        company="Example",
        role="Platform Engineer",
        job_description="A complete Platform Engineer job description for testing.",
    )
    analysis = JobAnalysis(
        company="Example",
        role="Platform Engineer",
        strong_matches=[],
        partial_matches=[],
        missing_requirements=[],
        supported_keywords=[],
        unsupported_keywords=[],
        recommendation="APPLY",
        match_level="HIGH",
        reasoning_summary="A valid deterministic test analysis.",
    )
    slug, _ = storage.save_application(job, analysis, TailoredResume.model_validate(resume_payload), [])
    return app, slug, store, storage


@pytest.mark.parametrize(
    ("filename", "mime", "image_format"),
    [("avatar.jpg", "image/jpeg", "JPEG"), ("avatar.png", "image/png", "PNG")],
)
def test_quick_avatar_endpoint_uploads_and_refreshes_artifacts(
    quick_photo_app, filename, mime, image_format
):
    app, slug, store, storage = quick_photo_app
    response = TestClient(app).post(
        f"/preview/{slug}/photo",
        files={"photo": (filename, image_bytes(image_format), mime)},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "photo_enabled": True}
    assert store.exists()
    _, _, _, metadata = storage.load_application(slug)
    assert metadata["photo_enabled"] is True
    assert storage.artifact(slug, "resume.pdf").is_file()
    assert storage.artifact(slug, "resume.docx").is_file()


@pytest.mark.skipif(not features.check("webp"), reason="Pillow was built without WEBP")
def test_quick_avatar_endpoint_accepts_webp(quick_photo_app):
    app, slug, store, _ = quick_photo_app
    response = TestClient(app).post(
        f"/preview/{slug}/photo",
        files={"photo": ("avatar.webp", image_bytes("WEBP"), "image/webp")},
    )
    assert response.status_code == 200
    assert store.exists()


def test_quick_avatar_rejects_invalid_and_oversized_files(quick_photo_app):
    app, slug, store, _ = quick_photo_app
    client = TestClient(app)
    invalid = client.post(
        f"/preview/{slug}/photo",
        files={"photo": ("avatar.jpg", b"not an image", "image/jpeg")},
    )
    assert invalid.status_code == 422
    assert not store.exists()

    app.state.settings.profile_photo_max_bytes = 20
    oversized = client.post(
        f"/preview/{slug}/photo",
        files={"photo": ("avatar.png", image_bytes("PNG"), "image/png")},
    )
    assert oversized.status_code == 422
    assert not store.exists()


def test_quick_avatar_replaces_removes_and_returns_to_initials(quick_photo_app, profile, resume_payload):
    app, slug, store, storage = quick_photo_app
    client = TestClient(app)
    first = client.post(
        f"/preview/{slug}/photo",
        files={"photo": ("first.png", image_bytes("PNG"), "image/png")},
    )
    assert first.status_code == 200
    original = store.path.read_bytes()
    replacement = client.post(
        f"/preview/{slug}/photo",
        files={"photo": ("next.jpg", image_bytes("JPEG", (160, 45, 45)), "image/jpeg")},
    )
    assert replacement.status_code == 200
    assert store.path.read_bytes() != original
    assert ProfilePhotoStore(store.directory).exists()

    hidden = client.post(f"/preview/{slug}/photo/hide")
    assert hidden.json()["photo_enabled"] is False
    assert store.exists()
    used = client.post(f"/preview/{slug}/photo/use")
    assert used.json()["photo_enabled"] is True

    removed = client.post(f"/preview/{slug}/photo/remove")
    assert removed.status_code == 200
    assert not store.exists()
    _, resume, _, metadata = storage.load_application(slug)
    assert metadata["photo_enabled"] is False
    html = app.state.pdf_generator.render_html(resume, profile, photo_enabled=True)
    assert "<span>JT</span>" in html
