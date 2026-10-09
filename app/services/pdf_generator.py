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
                    (guide.get("compact_headings"), "layout-tight-headings"),
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
        guide.pop("compact_headings", None)
        original = deepcopy(resume)
        fitted = deepcopy(resume)
        fitted.core_skills = fitted.core_skills[:16]
        for item in fitted.experience:
            item.bullets = item.bullets[:4]
        original = deepcopy(fitted)

        # 1. Remove Interests as first priority upon overflow
        if not self._fits_one_page(fitted, profile, guide) and fitted.interests:
            fitted.interests = []

        # 2. Shorten minor project descriptions
        for limit in (190, 140):
            if self._fits_one_page(fitted, profile, guide):
                break
            for project in sorted(fitted.projects, key=lambda item: len(item.description), reverse=True):
                project.description = self._shorten(project.description, limit)
                if self._fits_one_page(fitted, profile, guide):
                    break

        # Trim 3rd project if present and overflowing
        if not self._fits_one_page(fitted, profile, guide) and len(fitted.projects) > 2:
            fitted.projects = fitted.projects[:2]

        # 3. Reduce lower-priority skills gradually
        for min_skills in (14, 12, 10):
            if self._fits_one_page(fitted, profile, guide):
                break
            while not self._fits_one_page(fitted, profile, guide) and len(fitted.core_skills) > min_skills:
                fitted.core_skills.pop()
                if fitted.selected_skill_ids:
                    fitted.selected_skill_ids = fitted.selected_skill_ids[: len(fitted.core_skills)]

        # 4. Spacing tightened
        if not self._fits_one_page(fitted, profile, guide):
            guide["compact_spacing"] = True

        # Bullet spacing tightened
        if not self._fits_one_page(fitted, profile, guide):
            guide["compact_bullets"] = True

        # Heading spacing tightened
        if not self._fits_one_page(fitted, profile, guide):
            guide["compact_headings"] = True

        # 5. Shorten overly long summary in stages
        summary_target = max(350, min(500, int(guide.get("summary_max_chars", 500))))
        for target in (summary_target, 420, 360, 320):
            if self._fits_one_page(fitted, profile, guide):
                break
            if len(fitted.professional_summary) > target:
                fitted.professional_summary = self._shorten_summary(fitted.professional_summary, target)

        # Shorten longest bullets
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

        # 6. Remove lowest-relevance bullets as a last resort
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

        # Emergency overflow fallback only if still overflowing
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
            fitted.professional_summary = self._shorten_summary(fitted.professional_summary, 280)
        while not self._fits_one_page(fitted, profile, guide) and len(fitted.experience) > 4:
            fitted.experience.pop()

        # EXPAND to fill available space
        fitted = self._expand_to_available_space(fitted, original, profile, guide)
        return fitted, self._layout_warnings(original, fitted, guide)

    def _fits_one_page(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> bool:
        metrics = self._layout_metrics(resume, profile, guide)
        return bool(metrics["pages"] == 1 and metrics["main_fits"] and metrics["sidebar_fits"])

    def _layout_metrics(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> dict[str, float | bool]:
        document = HTML(string=self.render_html(resume, profile, guide), base_url=str(self.data_dir)).render()
        if not document.pages:
            return {"pages": 0, "main_fits": False, "sidebar_fits": False, "utilization": 1.0, "used_vertical_ratio": 1.0}
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
                "used_vertical_ratio": 1.0,
            }
        main = sections[0]
        # Main available space excluding footer / GDPR
        main_available = max(1.0, footer.position_y - main.position_y - 6)
        main_used = main.height
        used_vertical_ratio = main_used / main_available

        sidebar_bottom = max(
            (box.position_y + box.height for box in sidebar_sections),
            default=article.position_y,
        )
        article_bottom = article.position_y + article.height
        sidebar_available = max(1.0, article_bottom - article.position_y - 12)
        sidebar_used = max(0.0, sidebar_bottom - article.position_y)
        sidebar_ratio = sidebar_used / sidebar_available

        return {
            "pages": len(document.pages),
            "main_fits": main.position_y + main.height <= footer.position_y - 6,
            "sidebar_fits": sidebar_bottom <= article_bottom - 8,
            "used_vertical_ratio": used_vertical_ratio,
            "utilization": max(used_vertical_ratio, sidebar_ratio),
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
            metrics = self._layout_metrics(fitted, profile, guide)
            ratio = float(metrics.get("used_vertical_ratio", metrics.get("utilization", 1.0)))
            return ratio < 0.90

        max_iterations = 15
        iteration = 0

        while iteration < max_iterations and has_room():
            iteration += 1
            expanded = False

            # 1. Restore most relevant removed experience bullet
            for exp_idx, orig_exp in enumerate(original.experience):
                if exp_idx >= len(fitted.experience):
                    break
                fit_exp = fitted.experience[exp_idx]
                if len(fit_exp.bullets) < len(orig_exp.bullets):
                    next_bullet = orig_exp.bullets[len(fit_exp.bullets)]
                    candidate = deepcopy(fitted)
                    candidate.experience[exp_idx].bullets.append(deepcopy(next_bullet))
                    if self._fits_one_page(candidate, profile, guide):
                        fitted = candidate
                        expanded = True
                        break

            if expanded:
                continue

            # 2. Restore richer summary
            if len(fitted.professional_summary) < len(original.professional_summary):
                candidate = deepcopy(fitted)
                candidate.professional_summary = original.professional_summary
                if self._fits_one_page(candidate, profile, guide):
                    fitted = candidate
                    expanded = True
                    continue

            # 3. Restore relevant hard skill
            if len(fitted.core_skills) < len(original.core_skills):
                next_skill_idx = len(fitted.core_skills)
                candidate = deepcopy(fitted)
                candidate.core_skills.append(original.core_skills[next_skill_idx])
                if original.selected_skill_ids and next_skill_idx < len(original.selected_skill_ids):
                    candidate.selected_skill_ids.append(original.selected_skill_ids[next_skill_idx])
                if self._fits_one_page(candidate, profile, guide):
                    fitted = candidate
                    expanded = True
                    continue

            # 4. Restore project detail
            for proj_idx, orig_proj in enumerate(original.projects):
                if proj_idx >= len(fitted.projects):
                    candidate = deepcopy(fitted)
                    candidate.projects.append(deepcopy(orig_proj))
                    if self._fits_one_page(candidate, profile, guide):
                        fitted = candidate
                        expanded = True
                        break
                elif fitted.projects[proj_idx].description != orig_proj.description:
                    candidate = deepcopy(fitted)
                    candidate.projects[proj_idx].description = orig_proj.description
                    if self._fits_one_page(candidate, profile, guide):
                        fitted = candidate
                        expanded = True
                        break

            if expanded:
                continue

            # 5. Restore unshortened bullet text
            for exp_idx, fit_exp in enumerate(fitted.experience):
                orig_exp = original.experience[exp_idx]
                for b_idx, fit_b in enumerate(fit_exp.bullets):
                    if b_idx < len(orig_exp.bullets):
                        orig_b = orig_exp.bullets[b_idx]
                        if fit_b.text != orig_b.text:
                            candidate = deepcopy(fitted)
                            candidate.experience[exp_idx].bullets[b_idx].text = orig_b.text
                            if self._fits_one_page(candidate, profile, guide):
                                fitted = candidate
                                expanded = True
                                break
                if expanded:
                    break

            # 6. Restore interests if removed and space permits
            if original.interests and not fitted.interests:
                candidate = deepcopy(fitted)
                candidate.interests = list(original.interests)
                if self._fits_one_page(candidate, profile, guide):
                    fitted = candidate
                    expanded = True
                    continue

            if not expanded:
                break

        return fitted

    @staticmethod
    def _layout_warnings(original: TailoredResume, fitted: TailoredResume, guide: dict) -> list[str]:
        warnings = []
        if guide.get("compact_spacing"):
            warnings.append("Adaptive layout tightened section spacing")
        if guide.get("compact_bullets"):
            warnings.append("Adaptive layout tightened bullet spacing")
        if guide.get("compact_headings"):
            warnings.append("Adaptive layout tightened heading spacing")
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
        if original.interests and not fitted.interests:
            warnings.append("Adaptive layout removed interests section to fit page")
        if len(fitted.projects) < len(original.projects):
            warnings.append(
                f"Adaptive layout removed {len(original.projects) - len(fitted.projects)} lower-priority project(s) to fit page"
            )
        if len(fitted.experience) < len(original.experience):
            warnings.append("Adaptive layout removed older experience as an extreme overflow fallback")
        return warnings

    def _photo_data_uri(self) -> str:
        path = self.photo_store.path
        if path.is_file() and path.stat().st_size <= self.photo_store.max_bytes:
            mime = "image/webp" if path.suffix.casefold() == ".webp" else "image/jpeg"
            return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"
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
