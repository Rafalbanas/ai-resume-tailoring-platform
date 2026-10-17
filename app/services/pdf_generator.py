import base64
import hashlib
import json
import re
from contextlib import closing
from copy import deepcopy
from html import escape
from io import BytesIO
from pathlib import Path

import pypdfium2
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfReader
from weasyprint import HTML

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.languages import profile_languages
from app.services.professional_summary import deduplicate_summary
from app.services.profile_photo import ProfilePhotoStore
from app.services.resume_export import contacts, link_display, prepare_resume, validate_layout, validate_pdf_output


class PDFGenerator:
    def __init__(
        self,
        templates_dir: Path,
        static_dir: Path,
        data_dir: Path = Path("data"),
        photo_store: ProfilePhotoStore | None = None,
        *, isolated: bool = True,
    ):
        self.isolated = isolated
        self._preview_cache = {}
        self.env = Environment(loader=FileSystemLoader(templates_dir), autoescape=select_autoescape(["html"]))
        self.css_path = static_dir / "resume.css"
        self.data_dir = data_dir
        self.photo_store = photo_store or ProfilePhotoStore(data_dir / "profile_photo")

    def _processing_payload(self, resume, profile, guide=None, **options):
        from app.services.processing import encoded
        path = self.photo_store.jpg_path if self.photo_store.jpg_path.is_file() else self.photo_store.path
        return {'resume': resume.model_dump(mode='json'), 'profile': profile.model_dump(mode='json'),
                'guide': guide or {}, 'options': options,
                'photo': encoded(path.read_bytes()) if path.is_file() and path.stat().st_size <= self.photo_store.max_bytes else ''}

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
        resume = prepare_resume(resume, profile)
        resume.professional_summary = deduplicate_summary(resume.professional_summary, FactCatalog(profile))
        guide = layout_guide or {}
        if template_name not in {"modern_sidebar", "ats_classic"}:
            template_name = "modern_sidebar"
        include_photo = template_name == "modern_sidebar" and (
            self.photo_store.exists() if photo_enabled is None else photo_enabled and self.photo_store.exists()
        )
        order = ["summary", "experience", "education", "projects", "certifications"]
        if template_name == "modern_sidebar":
            requested = guide.get("section_order", order)
            order = list(dict.fromkeys([value for value in requested if value in order] + order))
        render_context = dict(
            resume=resume,
            personal=profile.personal,
            contacts=contacts(profile),
            link_display=link_display,
            languages=profile_languages(profile),
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
        css = f"<style>{self.css_path.read_text(encoding='utf-8')}</style>"
        template = self.env.get_template("resume.html")
        markup = template.render(**render_context)
        return ('<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
                f'<title>{escape(profile.personal.name)} — CV</title>{css}</head><body>{markup}</body></html>')

    def render_preview(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        layout_guide: dict | None = None,
        *,
        template_name: str = "modern_sidebar",
        photo_enabled: bool | None = None,
        interactive_photo: bool = False,
    ) -> str:
        """Show the PDF engine's actual pages, never reflow print CSS in a browser.

        Raster pages retain precise pagination; accessible text and clickable links
        come from the same PDF. The export itself remains searchable vector text.
        """
        if self.isolated:
            contacts(profile)
            from app.services.processing import process
            payload = self._processing_payload(resume, profile, layout_guide, template_name=template_name,
                photo_enabled=photo_enabled, interactive_photo=interactive_photo)
            key = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
            if key not in self._preview_cache:
                result = process('preview', payload)
                if len(result.encode()) > 8 * 1024 * 1024:
                    raise ValueError('Preview exceeds the size limit.')
                if len(self._preview_cache) >= 2:
                    del self._preview_cache[next(iter(self._preview_cache))]
                self._preview_cache[key] = result
            return self._preview_cache[key]
        markup = self.render_html(resume, profile, layout_guide, template_name=template_name,
                                  photo_enabled=photo_enabled)
        document = self._render_document(markup)
        validate_layout(document)
        pdf = document.write_pdf(pdf_tags=True)
        validate_pdf_output(pdf, profile)
        reader = PdfReader(BytesIO(pdf))
        if len(reader.pages) > 30:
            raise ValueError('CV exceeds the 30-page processing limit.')
        pages = []
        with closing(pypdfium2.PdfDocument(pdf)) as raster:
            for index, source in enumerate(reader.pages):
                with closing(raster[index]) as page:
                    bitmap = page.render(scale=1.6)
                    try:
                        output = BytesIO()
                        bitmap.to_pil().save(output, format="PNG")
                    finally:
                        bitmap.close()
                width, height = float(source.mediabox.width), float(source.mediabox.height)
                links = []
                for annotation in source.get("/Annots", []):
                    annotation = annotation.get_object()
                    target = annotation.get("/A", {}).get("/URI", "")
                    if not str(target).startswith(("https://", "http://", "mailto:")):
                        continue
                    left, bottom, right, top = map(float, annotation["/Rect"])
                    links.append(f'<a class="page-link" href="{escape(str(target), quote=True)}" '
                                 f'aria-label="{escape(str(target), quote=True)}" style="left:{left/width*100}%;'
                                 f'top:{(height-top)/height*100}%;width:{(right-left)/width*100}%;'
                                 f'height:{(top-bottom)/height*100}%"></a>')
                portrait = ""
                if index == 0 and interactive_photo and template_name == "modern_sidebar":
                    interactive = self.render_html(resume, profile, layout_guide, template_name=template_name,
                                                   photo_enabled=photo_enabled, interactive_photo=True)
                    control = BeautifulSoup(interactive, "html.parser").find(id="quick-photo-avatar")
                    boxes = [b for b in document.pages[0]._page_box.descendants()
                             if getattr(b, "element", None) is not None
                             and "portrait" in b.element.get("class", "").split()]
                    if control and boxes:
                        box = boxes[0]
                        control["style"] = (f"position:absolute;left:{box.border_box_x()/document.pages[0].width*100}%;"
                                            f"top:{box.border_box_y()/document.pages[0].height*100}%;"
                                            f"width:{box.border_width()/document.pages[0].width*100}%;"
                                            f"height:{box.border_height()/document.pages[0].height*100}%;margin:0")
                        portrait = str(control)
                data = base64.b64encode(output.getvalue()).decode()
                pages.append(f'<section class="preview-page" aria-label="CV page {index+1}">'
                             f'<img class="page-image" src="data:image/png;base64,{data}" '
                             f'alt="CV page {index+1} of {len(reader.pages)}">'
                             f'<pre class="visually-hidden">{escape(source.extract_text())}</pre>'
                             + "".join(links) + portrait + '</section>')
        return '<div class="paginated-preview">' + "".join(pages) + '</div>'

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
        if self.isolated:
            contacts(profile)
            from app.services.processing import decoded, process
            output.write_bytes(decoded(process('pdf', self._processing_payload(resume, profile, layout_guide,
                template_name=template_name, photo_enabled=photo_enabled))))
            return
        document = self._render_document(self.render_html(
            resume, profile, layout_guide, template_name=template_name, photo_enabled=photo_enabled
        ))
        validate_layout(document)
        pdf = document.write_pdf(pdf_tags=True)
        validate_pdf_output(pdf, profile)
        output.write_bytes(pdf)

    def _render_document(self, markup: str):
        """Floats cannot fragment safely: move overflow sections into normal flow.

        WeasyPrint may silently omit a float's final child while reporting one
        page. Detect actual rendered text and retain whole sections in the main
        flow; it can paginate without losing facts or reducing font size.
        """
        document = HTML(string=markup, base_url=str(self.data_dir)).render()
        soup = BeautifulSoup(markup, "html.parser")
        sidebar = soup.select_one("aside.resume-sidebar")
        if sidebar is None:
            return self._finish_document(markup, document)
        rendered = []
        for page in document.pages:
            for box in page._page_box.descendants():
                element = getattr(box, "element", None)
                if (element is not None and "resume-sidebar" in element.get("class", "").split()
                        and type(box).__name__ == "BlockBox"):
                    rendered.extend(b.text for b in box.descendants() if type(b).__name__ == "TextBox")
        def key(value):
            return re.sub(r"\W+", "", value).casefold()
        actual = key(" ".join(rendered))
        main = soup.select_one("main .main-sections")
        moved = False
        for section in list(sidebar.find_all("section", recursive=False)):
            if key(section.get_text(" ", strip=True)) not in actual:
                section.extract()
                section["class"] = ["overflow-section"]
                interest_list = section.select_one(".interest-list")
                if interest_list is not None:
                    paragraph = soup.new_tag("p")
                    paragraph.string = " · ".join(item.get_text(" ", strip=True) for item in interest_list.select("li"))
                    interest_list.replace_with(paragraph)
                    section["class"].append("interests-continuation")
                main.append(section)
                moved = True
        if moved:
            document = HTML(string=str(soup), base_url=str(self.data_dir)).render()
        if len(document.pages) > 1:
            # Adapt spacing, never font size or facts. Both preview and export
            # run this same path, including the float overflow repair above.
            original = BeautifulSoup(markup, "html.parser")
            article = original.select_one("article.modern-sidebar")
            if article is not None:
                classes = list(article.get("class", []))
                for spacing in ("layout-compact", "layout-tight-bullets"):
                    if spacing not in classes:
                        article["class"] = classes + [spacing]
                        return self._render_document(str(original))
        # This verifies every expected section remains text, including pages
        # created by long skills/languages/interests. No silent clipping allowed.
        actual_all = key(" ".join(b.text for p in document.pages for b in p._page_box.descendants()
                                  if type(b).__name__ == "TextBox"))
        for section in soup.select("section"):
            # Bullet markers are separate boxes; compare each paragraph/list
            # item rather than relying on a particular PDF reading order.
            for node in section.select("h2,h3,p,li"):
                if key(node.get_text(" ", strip=True)) not in actual_all:
                    raise ValueError("CV content was omitted during pagination; export stopped.")
        return self._finish_document(str(soup), document)

    @staticmethod
    def page_content_metrics(document):
        """Measure content, excluding running furniture and consent margins."""
        result = []
        for page in document.pages:
            text = []
            for box in page._page_box.descendants():
                element = getattr(box, "element", None)
                if element is not None and type(box).__name__ == "BlockBox" and "main-sections" in element.get("class", "").split():
                    text = [b for b in box.descendants() if type(b).__name__ == "TextBox" and b.text.strip()]
                    break
            result.append({"characters": sum(len(b.text) for b in text),
                           "height": max((b.position_y + b.height for b in text), default=0) - min((b.position_y for b in text), default=0),
                           "available_height": page._page_box.height})
        return result

    def _finish_document(self, markup, document):
        soup = BeautifulSoup(markup, "html.parser")
        metrics = self.page_content_metrics(document)
        # A small trailing fragment is repaired by moving whole sections, never
        # dropping a final project or shrinking text. Content is unchanged.
        if len(document.pages) > 1 and metrics[-1]["height"] < metrics[-1]["available_height"] * .20:
            sections = soup.select("main .main-sections > section")
            for section in reversed(sections):
                section["style"] = "break-before:page"
                candidate = HTML(string=str(soup), base_url=str(self.data_dir)).render()
                tail = self.page_content_metrics(candidate)[-1]
                if len(candidate.pages) <= len(document.pages) and self.page_content_metrics(candidate)[0]["height"] >= self.page_content_metrics(candidate)[0]["available_height"] * .20 and tail["height"] >= tail["available_height"] * .20:
                    document = candidate
                    break
                del section["style"]
            else:
                # A long paragraph cannot move as a complete section. Protect
                # enough continuation lines instead; font and content stay intact.
                widow_style = soup.new_tag("style")
                widow_style.string = ".resume-main p,.resume-main li{widows:16;orphans:4}"
                soup.head.append(widow_style)
                candidate = HTML(string=str(soup), base_url=str(self.data_dir)).render()
                tail = self.page_content_metrics(candidate)[-1]
                if len(candidate.pages) <= len(document.pages) and tail["height"] >= tail["available_height"] * .20:
                    document = candidate
                else:
                    # Many short entries can be redistributed without moving a
                    # whole experience section onto an otherwise empty page.
                    entries = soup.select("main .main-sections .entry")
                    for entry in reversed(entries[-12:]):
                        entry["style"] = "break-before:page"
                        candidate = HTML(string=str(soup), base_url=str(self.data_dir)).render()
                        tail = self.page_content_metrics(candidate)[-1]
                        first = self.page_content_metrics(candidate)[0]
                        if len(candidate.pages) <= len(document.pages) and tail["height"] >= tail["available_height"]*.20 and first["height"] >= first["available_height"]*.20:
                            document = candidate
                            break
                        del entry["style"]
                    else:
                        raise ValueError("A nearly empty continuation page remains; review content before export.")
        # Reserve the margin on all pages but print consent once on the final one.
        style = soup.new_tag("style")
        style.string = f"@page modern {{ @bottom-center {{content:none}} }} @page ats {{ @bottom-center {{content:none}} }} @page modern:nth({len(document.pages)}) {{ @bottom-center {{content:element(consent)}} }} @page ats:nth({len(document.pages)}) {{ @bottom-center {{content:element(consent)}} }}"
        soup.head.append(style)
        final = HTML(string=str(soup), base_url=str(self.data_dir)).render()
        if len(final.pages) != len(document.pages):
            raise ValueError("Consent changed pagination unexpectedly; export stopped.")
        return final

    def fit_resume(
        self,
        resume: TailoredResume,
        profile: CandidateProfile,
        layout_guide: dict | None = None,
        *,
        template_name: str = "modern_sidebar",
        job_text: str = "",
        one_page: bool = False,
        fact_validator=None,
    ) -> tuple[TailoredResume, list[str]]:
        fitted = deepcopy(resume)
        guide = layout_guide if layout_guide is not None else {}
        for key in ("compact_spacing", "compact_bullets", "compact_headings"):
            guide.pop(key, None)
        if template_name == "ats_classic":
            return fitted, []
        if one_page:
            if fact_validator is None:
                raise ValueError("One-page generation requires source validation.")
            from app.services.one_page_resume import select_one_page
            def fits(candidate):
                try:
                    return self._fits_one_page(candidate, profile, guide)
                except ValueError as exc:
                    if "nearly empty continuation page" not in str(exc):
                        raise
                    return False
            fitted, selections = select_one_page(fitted, fact_validator, job_text, fits)
            return fitted, selections + self._layout_warnings(resume, fitted, guide)
        # Existing/manual CVs retain their chosen content.
        if self._fits_one_page(fitted, profile, guide):
            return fitted, []
        for key in ("compact_spacing", "compact_bullets"):
            guide[key] = True
            if self._fits_one_page(fitted, profile, guide):
                return fitted, self._layout_warnings(resume, fitted, guide)
        # Pagination is presentation, not a second content generator. Preserve
        # the validated natural summary, evidence IDs and level-labelled skills.
        # Overflow sections move into normal flow in _render_document.
        return fitted, self._layout_warnings(resume, fitted, guide) + ["Full employment, education and projects retained across multiple pages; continuation balanced"]

    def _fits_one_page(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> bool:
        metrics = self._layout_metrics(resume, profile, guide)
        return bool(metrics["pages"] == 1 and metrics["main_fits"] and metrics["sidebar_fits"])

    def _layout_metrics(self, resume: TailoredResume, profile: CandidateProfile, guide: dict) -> dict[str, float | bool]:
        if self.isolated:
            from app.services.processing import process
            return process('metrics', self._processing_payload(resume, profile, guide))
        document = self._render_document(self.render_html(resume, profile, guide))
        if not document.pages:
            return {"pages": 0, "main_fits": False, "sidebar_fits": False, "utilization": 1.0, "used_vertical_ratio": 1.0}
        # Consent is in the reserved page margin, outside the content box.
        page = document.pages[0]._page_box
        sections = [b for b in page.descendants() if getattr(b, "element", None) is not None
                    and "main-sections" in b.element.get("class", "").split() and type(b).__name__ == "BlockBox"]
        sidebar_boxes = [b for b in page.descendants() if getattr(b, "element", None) is not None
                         and "resume-sidebar" in b.element.get("class", "").split() and type(b).__name__ == "BlockBox"]
        sidebar_bottom = max((b.position_y + b.height for b in sidebar_boxes), default=0)
        moved_skills = any(getattr(b, "element", None) is not None and "overflow-section" in b.element.get("class", "").split()
                           and any(getattr(c, "text", "").strip() == "SKILLS" for c in b.descendants()) for b in page.descendants())
        page_bottom = page.content_box_y() + page.height
        main_bottom = max((b.position_y + b.height for b in sections), default=0)
        ratio = main_bottom / max(1, page.height)
        return {"pages": len(document.pages), "main_fits": len(document.pages) == 1,
                "sidebar_fits": not moved_skills and sidebar_bottom <= page_bottom + 1, "utilization": ratio, "used_vertical_ratio": ratio}

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
