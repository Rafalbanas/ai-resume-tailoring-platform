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
            layout_classes=" ".join(
                value
                for enabled, value in (
                    (guide.get("compact_spacing"), "layout-compact"),
                    (guide.get("compact_bullets"), "layout-tight-bullets"),
                )
                if enabled
            ),
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
        guide = layout_guide if layout_guide is not None else {}
        guide.pop("compact_spacing", None)
        guide.pop("compact_bullets", None)
        original = deepcopy(resume)
        fitted = deepcopy(resume)
        fitted.core_skills = fitted.core_skills[:16]
        for item in fitted.experience:
            item.bullets = item.bullets[:4]
        original = deepcopy(fitted)

        if not self._fits_one_page(fitted, profile, guide):
            guide["compact_spacing"] = True
        if not self._fits_one_page(fitted, profile, guide):
            guide["compact_bullets"] = True

        summary_target = max(350, min(500, int(guide.get("summary_max_chars", 500))))
        if not self._fits_one_page(fitted, profile, guide) and len(fitted.professional_summary) > summary_target:
            fitted.professional_summary = self._shorten_summary(fitted.professional_summary, summary_target)

        for limit in (230, 195, 165):
            if self._fits_one_page(fitted, profile, guide):
                break
            longest = sorted(
                (bullet for item in fitted.experience for bullet in item.bullets if len(bullet.text) > limit),
                key=lambda bullet: len(bullet.text),
                reverse=True,
            )
            for bullet in longest:
                bullet.text = self._shorten(bullet.text, limit)

        while not self._fits_one_page(fitted, profile, guide) and len(fitted.core_skills) > 10:
            fitted.core_skills.pop()
            if fitted.selected_skill_ids:
                fitted.selected_skill_ids = fitted.selected_skill_ids[: len(fitted.core_skills)]

        for limit in (190, 140):
            if self._fits_one_page(fitted, profile, guide):
                break
            for project in sorted(fitted.projects, key=lambda item: len(item.description), reverse=True):
                project.description = self._shorten(project.description, limit)
                if self._fits_one_page(fitted, profile, guide):
                    break

        preferred_minimums = [2, 1, 2, 2]
        while not self._fits_one_page(fitted, profile, guide):
            removable = [
                (index, len(item.bullets))
                for index, item in enumerate(fitted.experience)
                if len(item.bullets) > preferred_minimums[min(index, len(preferred_minimums) - 1)]
            ]
            if not removable:
                break
            index = max(removable, key=lambda value: (value[1], value[0]))[0]
            fitted.experience[index].bullets.pop()

        # One bullet per role is an emergency fallback only after every less destructive adjustment.
        while not self._fits_one_page(fitted, profile, guide):
            removable = [
                (index, len(item.bullets))
                for index, item in enumerate(fitted.experience)
                if len(item.bullets) > 1
            ]
            if not removable:
                break
            index = max(removable, key=lambda value: (value[1], value[0]))[0]
            fitted.experience[index].bullets.pop()

        if not self._fits_one_page(fitted, profile, guide) and len(fitted.projects) > 1:
            fitted.projects = fitted.projects[:1]
        if not self._fits_one_page(fitted, profile, guide):
            fitted.professional_summary = self._shorten_summary(fitted.professional_summary, 320)
        while not self._fits_one_page(fitted, profile, guide) and len(fitted.experience) > 4:
            fitted.experience.pop()

        fitted = self._expand_to_available_space(fitted, original, profile, guide)
        return fitted, self._layout_warnings(original, fitted, guide)

    def _fits_one_page(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> bool:
        metrics = self._layout_metrics(resume, profile, guide)
        return metrics["pages"] == 1 and metrics["main_fits"] and metrics["sidebar_fits"]

    def _layout_metrics(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> dict[str, float | bool]:
        document = HTML(string=self.render_html(resume, profile, guide), base_url=str(self.data_dir)).render()
        if not document.pages:
            return {"pages": 0, "main_fits": False, "sidebar_fits": False, "utilization": 1.0}
        descendants = list(document.pages[0]._page_box.descendants())

        def blocks(class_name: str):
            return [
                box
                for box in descendants
                if type(box).__name__ in {"BlockBox", "GridBox"}
                and getattr(box, "element", None) is not None
                and class_name in box.element.get("class", "").split()
            ]

        sections = blocks("main-sections")
        footer = next(
            (
                box
                for box in descendants
                if type(box).__name__ == "AbsolutePlaceholder"
                and getattr(box, "element", None) is not None
                and box.element.tag == "footer"
            ),
            None,
        )
        article = next(iter(blocks("resume-document")), None)
        sidebar_sections = blocks("sidebar-section")
        if not sections or footer is None or article is None:
            return {
                "pages": len(document.pages),
                "main_fits": False,
                "sidebar_fits": False,
                "utilization": 1.0,
            }
        main = sections[0]
        main_available = max(1.0, footer.position_y - main.position_y - 6)
        main_used = main.height
        sidebar_bottom = max(
            (box.position_y + box.height for box in sidebar_sections),
            default=article.position_y,
        )
        article_bottom = article.position_y + article.height
        sidebar_available = max(1.0, article_bottom - article.position_y - 12)
        sidebar_used = max(0.0, sidebar_bottom - article.position_y)
        return {
            "pages": len(document.pages),
            "main_fits": main.position_y + main.height <= footer.position_y - 6,
            "sidebar_fits": sidebar_bottom <= article_bottom - 8,
            "utilization": max(main_used / main_available, sidebar_used / sidebar_available),
        }

    def _expand_to_available_space(
        self,
        fitted: TailoredResume,
        original: TailoredResume,
        profile: CandidateProfile,
        guide: dict,
    ) -> TailoredResume:
        if not self._fits_one_page(fitted, profile, guide):
            return fitted

        def has_room() -> bool:
            return float(self._layout_metrics(fitted, profile, guide)["utilization"]) < 0.9

        def keep_if_fits(candidate: TailoredResume) -> bool:
            if self._fits_one_page(candidate, profile, guide):
                return True
            return False

        # Restore valuable experience first, one bullet at a time.
        for index, source in enumerate(original.experience):
            if not has_room():
                break
            if index >= len(fitted.experience):
                break
            for bullet_index, bullet in enumerate(source.bullets):
                if not has_room():
                    break
                current = fitted.experience[index].bullets
                if bullet_index < len(current) and current[bullet_index] == bullet:
                    continue
                candidate = deepcopy(fitted)
                candidate_bullets = candidate.experience[index].bullets
                if bullet_index < len(candidate_bullets):
                    candidate_bullets[bullet_index] = deepcopy(bullet)
                else:
                    candidate_bullets.append(deepcopy(bullet))
                if keep_if_fits(candidate):
                    fitted = candidate

        if has_room():
            candidate = deepcopy(fitted)
            candidate.professional_summary = original.professional_summary
            if keep_if_fits(candidate):
                fitted = candidate

        for index, skill in enumerate(original.core_skills):
            if not has_room():
                break
            if skill in fitted.core_skills:
                continue
            candidate = deepcopy(fitted)
            candidate.core_skills.insert(min(index, len(candidate.core_skills)), skill)
            if original.selected_skill_ids and index < len(original.selected_skill_ids):
                candidate.selected_skill_ids.insert(
                    min(index, len(candidate.selected_skill_ids)), original.selected_skill_ids[index]
                )
            if keep_if_fits(candidate):
                fitted = candidate

        for index, project in enumerate(original.projects):
            if not has_room():
                break
            if index >= len(fitted.projects):
                candidate = deepcopy(fitted)
                candidate.projects.append(deepcopy(project))
            else:
                candidate = deepcopy(fitted)
                candidate.projects[index] = deepcopy(project)
            if keep_if_fits(candidate):
                fitted = candidate
        return fitted

    @staticmethod
    def _layout_warnings(original: TailoredResume, fitted: TailoredResume, guide: dict) -> list[str]:
        warnings = []
        if guide.get("compact_spacing"):
            warnings.append("Adaptive layout tightened section spacing")
        if guide.get("compact_bullets"):
            warnings.append("Adaptive layout tightened bullet spacing")
        if fitted.professional_summary != original.professional_summary:
            warnings.append(f"Adaptive layout shortened the professional summary to {len(fitted.professional_summary)} characters")
        shortened = sum(
            1
            for original_item, fitted_item in zip(original.experience, fitted.experience, strict=False)
            for original_bullet, fitted_bullet in zip(original_item.bullets, fitted_item.bullets, strict=False)
            if original_bullet.text != fitted_bullet.text
        )
        if shortened:
            warnings.append(f"Adaptive layout shortened {shortened} longest experience bullet(s)")
        removed_skills = len(original.core_skills) - len(fitted.core_skills)
        if removed_skills:
            warnings.append(f"Adaptive layout removed {removed_skills} lower-priority skill(s)")
        shortened_projects = sum(
            1
            for original_project, fitted_project in zip(original.projects, fitted.projects, strict=False)
            if original_project.description != fitted_project.description
        )
        if shortened_projects:
            warnings.append(f"Adaptive layout shortened {shortened_projects} project description(s)")
        removed_bullets = sum(
            max(0, len(original_item.bullets) - len(fitted_item.bullets))
            for original_item, fitted_item in zip(original.experience, fitted.experience, strict=False)
        )
        if removed_bullets:
            warnings.append(f"Adaptive layout removed {removed_bullets} experience bullet(s) as a last resort")
        if len(fitted.projects) < len(original.projects):
            warnings.append("Adaptive layout removed the less relevant project as an extreme overflow fallback")
        if len(fitted.experience) < len(original.experience):
            warnings.append("Adaptive layout removed older experience as an extreme overflow fallback")
        return warnings

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
