from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume


def generate_docx(
    resume: TailoredResume,
    profile: CandidateProfile,
    output: Path,
    *,
    photo_path: Path | None = None,
    photo_enabled: bool = False,
    template_name: str = "modern_sidebar",
) -> None:
    if not profile.personal.name.strip():
        raise ValueError("Candidate name is missing from the active master profile.")
    document = Document()
    section = document.sections[0]
    section.top_margin = section.bottom_margin = Inches(0.55)
    section.left_margin = section.right_margin = Inches(0.65)
    styles = document.styles
    styles["Normal"].font.name = "Arial"
    styles["Normal"].font.size = Pt(9.5)
    if photo_enabled and template_name == "modern_sidebar" and photo_path and photo_path.is_file():
        photo = document.add_paragraph()
        photo.alignment = WD_ALIGN_PARAGRAPH.CENTER
        photo.add_run().add_picture(str(photo_path), width=Inches(1.15), height=Inches(1.15))
    title = document.add_heading(profile.personal.name, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    contact = " · ".join(
        filter(
            None,
            [
                profile.personal.location,
                profile.personal.email,
                profile.personal.phone,
                profile.personal.linkedin,
                profile.personal.website,
                profile.personal.github,
            ],
        )
    )
    paragraph = document.add_paragraph(contact)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph(resume.headline).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if resume.professional_summary:
        document.add_heading("Professional Summary", level=1)
        document.add_paragraph(resume.professional_summary)
    if resume.core_skills:
        document.add_heading("Core Skills", level=1)
        document.add_paragraph(" • ".join(resume.core_skills))
    if resume.experience:
        document.add_heading("Experience", level=1)
        for item in resume.experience:
            document.add_heading(f"{item.title} — {item.company}", level=2)
            document.add_paragraph(item.dates)
            for bullet in item.bullets:
                document.add_paragraph(bullet.text, style="List Bullet")
    if resume.projects:
        document.add_heading("Selected Projects", level=1)
        for item in resume.projects:
            document.add_heading(item.name, level=2)
            document.add_paragraph(item.description)
    if resume.education:
        document.add_heading("Education", level=1)
        for item in resume.education:
            document.add_paragraph(f"{item.qualification} — {item.institution} ({item.dates})")
    if resume.certifications:
        document.add_heading("Certifications", level=1)
        for item in resume.certifications:
            document.add_paragraph(" · ".join(filter(None, [item.name, item.issuer, item.date])))
    document.save(output)
