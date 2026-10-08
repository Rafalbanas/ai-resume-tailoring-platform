import base64
from copy import deepcopy
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume


class PDFGenerator:
    def __init__(self, templates_dir: Path, static_dir: Path, data_dir: Path = Path("data")):
        self.env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
        self.css_path = static_dir / "resume.css"
        self.data_dir = data_dir

    def render_html(self, resume: TailoredResume, profile: CandidateProfile, layout_guide: dict | None = None) -> str:
        if not profile.personal.name.strip():
            raise ValueError("Candidate name is missing from the active master profile.")
        guide = layout_guide or {}
        order = guide.get("section_order", ["summary", "experience", "education", "projects", "certifications"])
        markup = self.env.get_template("resume.html").render(
            resume=resume,
            personal=profile.personal,
            photo_data_uri=self._photo_data_uri(),
            section_order=order,
        )
        return f"<style>{self.css_path.read_text(encoding='utf-8')}</style>{markup}"

    def generate(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        output: Path,
        layout_guide: dict | None = None,
    ) -> None:
        HTML(string=self.render_html(resume, profile, layout_guide), base_url=str(self.data_dir)).write_pdf(output)

    def fit_resume(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        layout_guide: dict | None = None,
    ) -> tuple[TailoredResume, list[str]]:
        guide = layout_guide or {}
        fitted = deepcopy(resume)
        warnings = []
        summary_limit = int(guide.get("summary_max_chars", 520))
        if len(fitted.professional_summary) > summary_limit:
            fitted.professional_summary = self._shorten(fitted.professional_summary, summary_limit)
            warnings.append(f"Reference layout limited the professional summary to {summary_limit} characters")
        fitted.core_skills = fitted.core_skills[: int(guide.get("max_skills", 12))]
        max_bullets = int(guide.get("max_bullets_per_role", 4))
        for item in fitted.experience:
            item.bullets = item.bullets[:max_bullets]
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        for limit in (210, 160):
            for item in fitted.experience:
                for bullet in item.bullets:
                    bullet.text = self._shorten(bullet.text, limit)
            warnings.append(f"Layout fit shortened experience bullets to {limit} characters")
            if self._fits_one_page(fitted, profile, guide):
                return fitted, warnings

        fitted.core_skills = fitted.core_skills[:8]
        warnings.append("Layout fit limited core skills to the eight most relevant items")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        for item in fitted.experience:
            item.bullets = item.bullets[:2]
        fitted.projects = fitted.projects[:1]
        warnings.append("Layout fit reduced secondary bullets and projects")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        for item in fitted.experience:
            item.bullets = item.bullets[:1]
        fitted.projects = fitted.projects[:1]
        fitted.certifications = fitted.certifications[:2]
        warnings.append("Layout fit kept one verified bullet per role and one project")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        fitted.professional_summary = self._shorten(fitted.professional_summary, 320)
        fitted.experience = fitted.experience[:4]
        fitted.education = fitted.education[:2]
        fitted.certifications = fitted.certifications[:1]
        while len(fitted.experience) > 1 and not self._fits_one_page(fitted, profile, guide):
            fitted.experience.pop()
        warnings.append("Layout fit limited older experience to preserve a one-page A4 document")
        return fitted, warnings

    def _page_count(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> int:
        document = HTML(string=self.render_html(resume, profile, guide), base_url=str(self.data_dir)).render()
        return len(document.pages)

    def _fits_one_page(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> bool:
        text_units = len(resume.professional_summary)
        text_units += sum(len(bullet.text) for item in resume.experience for bullet in item.bullets)
        text_units += sum(len(item.description) for item in resume.projects)
        text_units += 80 * (len(resume.experience) + len(resume.education) + len(resume.projects))
        return text_units <= 3_800 and self._page_count(resume, profile, guide) <= 1

    def _photo_data_uri(self) -> str:
        mime_types = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}
        for path in sorted(self.data_dir.glob("profile_photo.*")):
            mime = mime_types.get(path.suffix.lower())
            if mime and path.is_file() and path.stat().st_size <= 5_000_000:
                return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
        return ""

    @staticmethod
    def _shorten(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        shortened = value[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
        return f"{shortened}."
