from pathlib import Path

from pypdf import PdfReader

from app.models.resume import TailoredResume
from app.services.pdf_generator import PDFGenerator


def test_pdf_generation(tmp_path, profile, resume_payload):
    output = tmp_path / "resume.pdf"
    PDFGenerator(Path("templates"), Path("static")).generate(TailoredResume.model_validate(resume_payload), profile, output)
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 1_000
    assert len(PdfReader(output).pages) == 1


def test_modern_sidebar_contains_fixed_sections_and_gdpr(profile, resume_payload):
    html = PDFGenerator(Path("templates"), Path("static")).render_html(
        TailoredResume.model_validate(resume_payload), profile
    )
    assert "modern-sidebar" in html
    assert "resume-sidebar" in html
    assert "Professional Summary" in html
    assert "GDPR" in html


def test_adaptive_page_fit_uses_shrink_order_and_keeps_one_page(tmp_path, profile, resume_payload):
    payload = dict(resume_payload)
    payload["core_skills"] = ["Python", "Linux", "n8n"] * 6
    experience = payload["experience"][0]
    experience["bullets"] = [
        {"text": "Verified operational improvement " * 20, "source_fact_ids": ["experience:0:fact:0"]}
        for _ in range(4)
    ]
    payload["experience"] = [dict(experience) for _ in range(8)]
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    fitted, warnings = generator.fit_resume(TailoredResume.model_validate(payload), profile)
    output = tmp_path / "fitted.pdf"
    generator.generate(fitted, profile, output)

    assert warnings
    assert warnings[:2] == [
        "Adaptive layout tightened section spacing",
        "Adaptive layout tightened bullet spacing",
    ]
    warning_text = " ".join(warnings)
    assert warning_text.index("shortened") < warning_text.index("lower-priority skill")
    assert len(PdfReader(output).pages) == 1


def test_page_fit_retains_multiple_bullets_when_layout_has_room(profile, resume_payload):
    payload = dict(resume_payload)
    payload["experience"][0]["bullets"] = [
        {"text": "Verified Python automation.", "source_fact_ids": ["experience:0:fact:0"]},
        {"text": "Verified Linux operations.", "source_fact_ids": ["experience:0:fact:0"]},
        {"text": "Verified incident support.", "source_fact_ids": ["experience:0:fact:0"]},
    ]
    fitted, warnings = PDFGenerator(Path("templates"), Path("static")).fit_resume(
        TailoredResume.model_validate(payload), profile, {}
    )

    assert len(fitted.experience[0].bullets) == 3
    assert not any("experience bullet(s) as a last resort" in warning for warning in warnings)


def test_expand_to_fit_restores_valuable_bullet(profile, resume_payload, monkeypatch):
    generator = PDFGenerator(Path("templates"), Path("static"))
    original = TailoredResume.model_validate(resume_payload)
    original.experience[0].bullets.append(
        original.experience[0].bullets[0].model_copy(update={"text": "Second verified operational improvement."})
    )
    fitted = original.model_copy(deep=True)
    fitted.experience[0].bullets = fitted.experience[0].bullets[:1]
    monkeypatch.setattr(
        generator,
        "_fits_one_page",
        lambda resume, _profile, _guide: len(resume.experience[0].bullets) <= 2,
    )
    monkeypatch.setattr(
        generator,
        "_layout_metrics",
        lambda resume, _profile, _guide: {"utilization": 0.7 + 0.1 * len(resume.experience[0].bullets)},
    )

    expanded = generator._expand_to_available_space(fitted, original, profile, {})

    assert len(expanded.experience[0].bullets) == 2
