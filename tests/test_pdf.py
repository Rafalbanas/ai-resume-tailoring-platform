from pathlib import Path

from app.models.resume import TailoredResume
from app.services.pdf_generator import PDFGenerator


def test_pdf_generation(tmp_path, profile, resume_payload):
    output = tmp_path / "resume.pdf"
    PDFGenerator(Path("templates"), Path("static")).generate(TailoredResume.model_validate(resume_payload), profile, output)
    assert output.read_bytes().startswith(b"%PDF")
    assert output.stat().st_size > 1_000
