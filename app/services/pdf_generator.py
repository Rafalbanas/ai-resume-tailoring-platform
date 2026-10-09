import base64
from copy import deepcopy
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume
from app.services.profile_photo import ProfilePhotoStore


class PDFGenerator:
    def __init__(
        self,
        templates_dir: Path,
        static_dir: Path,
        data_dir: Path = Path("data"),
        photo_store: ProfilePhotoStore | None = None,
    ):
        self.env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
        self.css_path = static_dir / "resume.css"
        self.data_dir = data_dir
        self.photo_store = photo_store or ProfilePhotoStore(data_dir / "profile_photo")

    def render_html(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        layout_guide: dict | None = None,
        *,
        template_name: str = "modern_sidebar",
        photo_enabled: bool | None = None,
        interactive_photo: bool = False,
    ) -> str:
        if not profile.personal.name.strip():
            raise ValueError("Candidate name is missing from the active master profile.")
        guide = layout_guide or {}
        if template_name not in {"modern_sidebar", "ats_classic"}:
            template_name = "modern_sidebar"
        include_photo = template_name == "modern_sidebar" and (
            self.photo_store.exists() if photo_enabled is None else photo_enabled and self.photo_store.exists()
        )
        order = guide.get("section_order", ["summary", "experience", "education", "projects", "certifications"])
        markup = self.env.get_template("resume.html").render(
            resume=resume,
            personal=profile.personal,
            template_name=template_name,
            photo_enabled=include_photo,
            photo_available=self.photo_store.exists(),
            interactive_photo=interactive_photo and template_name == "modern_sidebar",
            photo_data_uri=self._photo_data_uri() if include_photo else "",
            initials="".join(part[0] for part in profile.personal.name.split() if part)[:2].upper() or "CV",
            section_order=order,
        )
        return f"<style>{self.css_path.read_text(encoding='utf-8')}</style>{markup}"

    def generate(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        output: Path,
        layout_guide: dict | None = None,
        *,
        template_name: str = "modern_sidebar",
        photo_enabled: bool | None = None,
    ) -> None:
        HTML(
            string=self.render_html(
                resume, profile, layout_guide, template_name=template_name, photo_enabled=photo_enabled
            ),
            base_url=str(self.data_dir),
        ).write_pdf(output)

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
            shortened_summary = self._shorten_summary(fitted.professional_summary, summary_limit)
            if shortened_summary != fitted.professional_summary:
                fitted.professional_summary = shortened_summary
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
        warnings.append("Layout fit reduced secondary experience bullets")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        for item in fitted.experience:
            item.bullets = item.bullets[:1]
        warnings.append("Layout fit kept one verified bullet per role")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        fitted.projects = fitted.projects[:1]
        fitted.certifications = fitted.certifications[:2]
        warnings.append("Layout fit limited projects to the most relevant item")
        if self._fits_one_page(fitted, profile, guide):
            return fitted, warnings

        fitted.professional_summary = self._shorten_summary(fitted.professional_summary, 320)
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
        text_units += 35 * len(resume.core_skills)
        text_units += 2 * len(resume.headline)
        # WeasyPrint reports one page even when a fixed A4 grid clips overflowing content.
        # Keep a conservative density budget so projects and the fixed GDPR footer remain visible.
        return text_units <= 2_200 and self._page_count(resume, profile, guide) <= 1

    def _photo_data_uri(self) -> str:
        path = self.photo_store.path
        if path.is_file() and path.stat().st_size <= self.photo_store.max_bytes:
            return f"data:image/jpeg;base64,{base64.b64encode(path.read_bytes()).decode()}"
        return ""

    @staticmethod
    def _shorten(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        shortened = value[: limit + 1].rsplit(" ", 1)[0].rstrip(" ,;:.-")
        return f"{shortened}."

    @staticmethod
    def _shorten_summary(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        boundary = max(value.rfind(". ", 0, limit), value.rfind("! ", 0, limit), value.rfind("? ", 0, limit))
        return value[: boundary + 1].strip() if boundary >= 0 else value
