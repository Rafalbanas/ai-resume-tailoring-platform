from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume
from app.services.languages import profile_languages


def add_link(paragraph, text: str, target: str) -> None:
    link = OxmlElement("w:hyperlink")
    link.set(qn("r:id"), paragraph.part.relate_to(target, RT.HYPERLINK, is_external=True))
    run = OxmlElement("w:r")
    node = OxmlElement("w:t")
    node.text = text
    run.append(node)
    link.append(run)
    paragraph._p.append(link)


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
    styles["Normal"].font.size = Pt(10.5)
    styles["Title"].font.size = Pt(24)
    styles["Heading 1"].font.size = Pt(12)
    styles["Heading 2"].font.size = Pt(10.5)
    section.page_width = Inches(8.2677)
    section.page_height = Inches(11.6929)
    if photo_enabled and template_name == "modern_sidebar" and photo_path and photo_path.is_file():
        actual_photo = photo_path
        if actual_photo.suffix.casefold() == ".webp":
            sibling_jpg = actual_photo.with_name("current.jpg")
            if sibling_jpg.is_file():
                actual_photo = sibling_jpg
            else:
                import tempfile

                from PIL import Image
                with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
                    tmp_path = Path(tmp.name)
                try:
                    with Image.open(actual_photo) as img:
                        img.convert("RGB").save(tmp_path, "JPEG")
                    actual_photo = tmp_path
                except Exception:
                    actual_photo = None
        if actual_photo and actual_photo.is_file():
            photo = document.add_paragraph()
            photo.alignment = WD_ALIGN_PARAGRAPH.CENTER
            photo.add_run().add_picture(str(actual_photo), width=Inches(1.15), height=Inches(1.15))
    title = document.add_heading(profile.personal.name, level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph = document.add_paragraph()
    values = [profile.personal.location, profile.personal.email, profile.personal.phone,
              profile.personal.linkedin, profile.personal.website, profile.personal.github]
    for value in filter(None, values):
        if paragraph.text or len(paragraph._p):
            paragraph.add_run(" · ")
        if value == profile.personal.email:
            add_link(paragraph, value, f"mailto:{value}")
        elif value.startswith(("https://", "http://")):
            add_link(paragraph, value, value)
        else:
            paragraph.add_run(value)
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    document.add_paragraph(resume.headline).alignment = WD_ALIGN_PARAGRAPH.CENTER
    if resume.professional_summary:
        document.add_heading("Professional Summary", level=1)
        document.add_paragraph(resume.professional_summary)
    if resume.core_skills:
        document.add_heading("Core Skills", level=1)
        document.add_paragraph(" • ".join(resume.core_skills))
    if profile_languages(profile):
        document.add_heading("Languages", level=1)
        document.add_paragraph(" · ".join(profile_languages(profile)))
    if resume.experience:
        document.add_heading("Experience", level=1)
        for item in resume.experience:
            document.add_heading(f"{item.title} — {item.company}", level=2)
            date_paragraph = document.add_paragraph(item.dates)
            date_paragraph.paragraph_format.keep_with_next = True
            for bullet in item.bullets:
                document.add_paragraph(bullet.text, style="List Bullet")
    if resume.education:
        document.add_heading("Education", level=1)
        for item in resume.education:
            education_paragraphs = [document.add_paragraph(f"{item.qualification} — {item.institution} ({item.dates})")]
            if getattr(item, "specialisation", None):
                education_paragraphs.append(document.add_paragraph(item.specialisation))
            if getattr(item, "thesis_subline", None):
                education_paragraphs.append(document.add_paragraph(item.thesis_subline))
            for index, entry in enumerate(education_paragraphs):
                entry.paragraph_format.keep_together = True
                entry.paragraph_format.keep_with_next = index < len(education_paragraphs) - 1
    if resume.projects:
        document.add_heading("Selected Projects", level=1)
        for item in resume.projects:
            document.add_heading(item.name, level=2)
            if item.url:
                add_link(document.add_paragraph(), item.url, item.url)
            document.add_paragraph(item.description)
            if item.technologies:
                document.add_paragraph(" · ".join(item.technologies))
    if resume.certifications:
        document.add_heading("Certifications", level=1)
        for item in resume.certifications:
            document.add_paragraph(" · ".join(filter(None, [item.name, item.issuer, item.date])))
    if getattr(resume, "interests", None):
        document.add_heading("Interests", level=1)
        document.add_paragraph(" • ".join(resume.interests))
    consent = document.add_paragraph("I consent to the processing of my personal data for recruitment purposes in accordance with applicable data protection law (GDPR).")
    for run in consent.runs:
        run.font.size = Pt(9)
    document.save(output)
