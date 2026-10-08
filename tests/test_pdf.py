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


def test_page_fit_shortens_content_before_reducing_skills(tmp_path, profile, resume_payload):
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
    assert any("shortened experience bullets" in warning for warning in warnings)
    assert len(PdfReader(output).pages) == 1
