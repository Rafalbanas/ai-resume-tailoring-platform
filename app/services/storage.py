import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from pydantic import ValidationError

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse


class DraftDataError(ValueError):
    """A stored draft exists, but cannot be safely used."""


def safe_filename(value: str, fallback: str = "item") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return (cleaned[:80] or fallback).strip(".-")


def _compact_label(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    prefix = value[:limit + 1].rsplit("-", 1)[0]
    return prefix if limit // 2 <= len(prefix) <= limit else value[:limit].rstrip("-")


def _company_label(company: str) -> str:
    company = safe_filename(company, "firma")
    company = re.sub(
        r"(?:^|-)(?:spolka-z-ograniczona-odpowiedzialnoscia|sp-z-o-o|sp-z-oo|s-a|sa|ltd|limited|llc|inc|gmbh)(?=-|$)",
        "-", company,
    )
    company = re.sub(r"(?:^|-)resources(?=-|$)", "-", company)
    return re.sub(r"-+", "-", company).strip("-") or "firma"


def _role_label(role: str) -> str:
    replacements = {
        "planning": "plan", "systems": "sys", "consultant": "cons",
        "analysis": "anal", "engineer": "eng", "developer": "dev",
        "specialist": "spec", "senior": "sr", "junior": "jr", "manager": "mgr",
    }
    normalized = safe_filename(role, "rola").replace("supply-chain-planning", "supply-plan")
    words = normalized.split("-")
    words = [replacements.get(word, word) for word in words if word not in {"and", "of", "the", "platform"}]
    # Preserve short technology names near the end of long job titles (SQL, OMP, etc.).
    technical = [word for word in words if len(word) <= 3 and word not in replacements.values()]
    descriptive = [word for word in words if word not in technical]
    return "-".join(descriptive[:2] + list(dict.fromkeys(technical)) + descriptive[2:]) or "rola"


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.generated_dir = data_dir / "generated"
        self.drafts_dir = data_dir / ".drafts"
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def download_filename(self, slug: str, kind: str, metadata: dict) -> str:
        """Name both existing and new exports within the upload portal's 50-character limit."""
        if kind not in {"pdf", "docx"}:
            raise ValueError("Unsupported export format")
        self.application_folder(slug)
        digest = hashlib.sha256(slug.encode()).hexdigest()
        other_digests = [
            hashlib.sha256(folder.name.encode()).hexdigest()
            for folder in self.generated_dir.iterdir() if folder.is_dir() and folder.name != slug
        ]
        id_length = 6
        while any(other.startswith(digest[:id_length]) for other in other_digests):
            id_length += 1
        identifier = digest[:id_length]
        date = datetime.fromisoformat(metadata["date"]).strftime("%y-%m-%d")
        # Reserve date, identifier, three separators and the complete extension first.
        budget = 50 - len(date) - len(identifier) - 3 - len(f".{kind}")
        company = _compact_label(_company_label(metadata["company"]), min(12, budget // 2))
        role = _compact_label(_role_label(metadata["role"]), budget - len(company))
        return f"{date}_{company}_{role}_{identifier}.{kind}"

    def save_draft(self, job: JobRequest, response: WorkflowResponse) -> str:
        draft_id = uuid4().hex
        payload = {"job": job.model_dump(mode="json"), "response": response.model_dump(mode="json"),
                   "created_at": datetime.now(timezone.utc).isoformat()}
        self._bound_draft_summary(payload)
        self._validate_draft(payload)
        destination = self.drafts_dir / f"{draft_id}.json"
        # Publish only complete files, on the same filesystem as the destination.
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.drafts_dir,
                                         suffix=".tmp", delete=False) as stream:
            temporary = Path(stream.name)
            try:
                json.dump(payload, stream, indent=2, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            except BaseException:
                temporary.unlink(missing_ok=True)
                raise
        try:
            os.replace(temporary, destination)
            self.load_draft(draft_id)
        except BaseException:
            temporary.unlink(missing_ok=True)
            destination.unlink(missing_ok=True)
            raise
        return draft_id

    def load_draft(self, draft_id: str) -> tuple[JobRequest, WorkflowResponse]:
        if not re.fullmatch(r"[a-f0-9]{32}", draft_id):
            raise FileNotFoundError(draft_id)
        try:
            payload = json.loads((self.drafts_dir / f"{draft_id}.json").read_text(encoding="utf-8"))
            return self._validate_draft(payload)
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise DraftDataError("Draft data could not be validated") from exc

    @classmethod
    def _validate_draft(cls, payload: dict) -> tuple[JobRequest, WorkflowResponse]:
        try:
            cls._bound_draft_summary(payload)
            return JobRequest.model_validate(payload["job"]), WorkflowResponse.model_validate(payload["response"])
        except (ValidationError, KeyError, TypeError, AttributeError) as exc:
            raise DraftDataError("Draft data could not be validated") from exc

    @staticmethod
    def _bound_draft_summary(payload: dict) -> None:
        # Older analyses may have been mutated beyond the model's field limit.
        # Keep the complete issue lists while bounding their display summary.
        analysis = payload.get("response", {}).get("analysis", {})
        summary = analysis.get("reasoning_summary")
        limit = JobAnalysis.model_fields["reasoning_summary"].metadata
        maximum = next(item.max_length for item in limit if hasattr(item, "max_length"))
        if isinstance(summary, str):
            analysis["reasoning_summary"] = summary[:maximum]

    def save_application(
        self,
        job: JobRequest,
        analysis: JobAnalysis,
        resume: TailoredResume,
        warnings: list[str],
        layout_guide: dict | None = None,
        draft_id: str | None = None,
        template_name: str = "modern_sidebar",
        photo_enabled: bool = False,
        truth_lock_warnings: list[str] | None = None,
        layout_warnings: list[str] | None = None,
        pre_fit_resume: TailoredResume | None = None,
        provider_used: str = "unknown",
        model_used: str = "unknown",
        fallback_used: bool = False,
        fallback_reason: str | None = None,
        retrieval_context: dict | None = None,
        truth_lock_enabled: bool = True,
    ) -> tuple[str, Path]:
        date = datetime.now(timezone.utc).date().isoformat()
        base = f"{date}_{safe_filename(job.company)}_{safe_filename(job.role)}"
        slug = base
        counter = 2
        while (self.generated_dir / slug).exists():
            slug = f"{base}_{counter}"
            counter += 1
        folder = self.generated_dir / slug
        folder.mkdir(parents=True)
        (folder / "job.txt").write_text(job.job_description, encoding="utf-8")
        (folder / "job.json").write_text(job.model_dump_json(indent=2), encoding="utf-8")
        (folder / "analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        (folder / "resume.generated.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        if pre_fit_resume:
            (folder / "pre_fit_resume.json").write_text(pre_fit_resume.model_dump_json(indent=2), encoding="utf-8")
        metadata = {
            "workflow": job.workflow,
            "cv_name": job.cv_name or (job.role if job.workflow == "custom" else f"{job.company} · {job.role}"),
            "source_cv": job.source_cv,
            "company": job.company,
            "role": job.role,
            "job_url": str(job.job_url) if job.job_url else None,
            "date": date,
            "match_level": analysis.match_level,
            "analysis_reliable": analysis.is_reliable,
            "analysis_uncertain": any(r.interpretation_uncertain for r in analysis.requirements),
            "analysis_method": analysis.analysis_method,
            "document_status": "pending_export",
            "candidate_data_status": "export fields checked" if truth_lock_enabled else "Manual content — source validation disabled",
            "truth_lock_enabled": truth_lock_enabled,
            "recommendation": analysis.recommendation,
            "warnings": warnings,
            "generation_warnings": warnings,
            "truth_lock_warnings": truth_lock_warnings if truth_lock_warnings is not None else [],
            "layout_warnings": layout_warnings or [],
            "layout_adjustments": layout_warnings or [],
            "layout_guide": layout_guide or {},
            "draft_id": draft_id,
            "template_name": template_name,
            "photo_enabled": bool(photo_enabled),
            "provider_used": provider_used,
            "model_used": model_used,
            "fallback_used": bool(fallback_used),
            "fallback_reason": fallback_reason,
            "retrieval_context": retrieval_context or {},
            "pre_fit_available": pre_fit_resume is not None,
            "summary_attestation": resume.summary_attestation,
            "generated_summary_attestation": resume.summary_attestation,
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return slug, folder

    def mark_export_checked(self, slug: str) -> None:
        folder = self.application_folder(slug)
        if not all((folder/name).is_file() for name in ('resume.pdf', 'resume.docx')):
            raise ValueError('Both CV exports must exist before marking the document checked.')
        path = folder/'metadata.json'
        metadata = json.loads(path.read_text())
        metadata['document_status'] = 'layout_and_exports_checked'
        path.write_text(json.dumps(metadata, indent=2))

    def confirm_summary(self, slug: str, token: str) -> None:
        folder = self.application_folder(slug)
        path = folder / 'metadata.json'
        metadata = json.loads(path.read_text())
        metadata['summary_confirmation'] = token
        metadata['summary_confirmed_at'] = datetime.now(timezone.utc).isoformat()
        fd, temporary = tempfile.mkstemp(dir=folder, prefix='.summary-confirmation-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(metadata, stream, indent=2)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def rename_application(self, slug: str, name: str) -> None:
        """Renames the application by updating the cv_name in metadata."""
        name = name.strip()
        if not (1 <= len(name) <= 150):
            raise ValueError("Name must be between 1 and 150 characters.")

        folder = self.application_folder(slug)
        path = folder / 'metadata.json'
        metadata = json.loads(path.read_text(encoding="utf-8"))
        metadata['cv_name'] = name

        fd, temporary = tempfile.mkstemp(dir=folder, prefix='.rename-')
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(metadata, stream, indent=2)
            os.replace(temporary, path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def duplicate_application(self, slug: str) -> str:
        """Duplicates the application folder and metadata, returning the new slug."""
        source_folder = self.application_folder(slug)
        metadata = json.loads((source_folder / "metadata.json").read_text(encoding="utf-8"))

        new_slug = f"{slug[:207]}-{uuid4().hex}"

        original_name = metadata.get("cv_name", "resume")
        new_name = f"{original_name} (copy)"
        if len(new_name) > 150:
            new_name = new_name[:150]

        tmp_dir = Path(tempfile.mkdtemp(dir=self.generated_dir, prefix=".duplicate_"))
        try:
            # mkdtemp already creates the directory, so copytree needs dirs_exist_ok=True
            shutil.copytree(source_folder, tmp_dir, dirs_exist_ok=True)

            tmp_metadata_path = tmp_dir / "metadata.json"
            tmp_metadata = json.loads(tmp_metadata_path.read_text(encoding="utf-8"))
            tmp_metadata["cv_name"] = new_name
            tmp_metadata.pop("summary_confirmation", None)
            tmp_metadata.pop("summary_confirmed_at", None)

            with open(tmp_metadata_path, "w", encoding="utf-8") as f:
                json.dump(tmp_metadata, f, indent=2)

            final_path = self.generated_dir / new_slug
            os.replace(tmp_dir, final_path)
            return new_slug
        finally:
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)

    def application_folder(self, slug: str) -> Path:
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,240}", slug):
            raise FileNotFoundError(slug)
        folder = (self.generated_dir / slug).resolve()
        if self.generated_dir.resolve() not in folder.parents or not folder.is_dir():
            raise FileNotFoundError(slug)
        return folder

    def load_application(self, slug: str) -> tuple[JobRequest, TailoredResume, TailoredResume, dict]:
        folder = self.application_folder(slug)
        metadata = json.loads((folder / "metadata.json").read_text(encoding="utf-8"))
        resume = TailoredResume.model_validate_json((folder / "resume.json").read_text(encoding="utf-8"))
        generated_path = folder / "resume.generated.json"
        generated = TailoredResume.model_validate_json(
            (generated_path if generated_path.is_file() else folder / "resume.json").read_text(encoding="utf-8")
        )
        job_path = folder / "job.json"
        if job_path.is_file():
            job = JobRequest.model_validate_json(job_path.read_text(encoding="utf-8"))
        else:
            job = JobRequest(
                company=metadata["company"],
                role=metadata["role"],
                job_url=metadata.get("job_url"),
                job_description=(folder / "job.txt").read_text(encoding="utf-8"),
            )
        resume.summary_attestation = metadata.get('summary_attestation', '')
        generated.summary_attestation = metadata.get('generated_summary_attestation', '')
        return job, resume, generated, metadata

    def save_current_resume(
        self,
        slug: str,
        resume: TailoredResume,
        warnings: list[str],
        *,
        template_name: str | None = None,
        photo_enabled: bool | None = None,
        truth_lock_warnings: list[str] | None = None,
        layout_warnings: list[str] | None = None,
        modern_photo_enabled: bool | None = None,
    ) -> Path:
        if template_name is not None and template_name not in {"modern_sidebar", "ats_classic"}:
            raise ValueError("Unsupported resume layout")
        folder = self.application_folder(slug)
        (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        metadata_path = folder / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["warnings"] = warnings
        metadata['summary_attestation'] = resume.summary_attestation
        if truth_lock_warnings is not None:
            metadata["truth_lock_warnings"] = truth_lock_warnings
        if layout_warnings is not None:
            metadata["layout_warnings"] = layout_warnings
            metadata["layout_adjustments"] = layout_warnings
        if photo_enabled is not None:
            metadata["photo_enabled"] = bool(photo_enabled)
        if template_name is not None:
            if template_name not in {"modern_sidebar", "ats_classic"}:
                raise ValueError("Unsupported resume layout")
            metadata["template_name"] = template_name
        if modern_photo_enabled is not None:
            metadata["modern_photo_enabled"] = modern_photo_enabled
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return folder

    def update_presentation(self, slug: str, *, photo_enabled: bool, template_name: str | None = None,
                            modern_photo_enabled: bool | None = None) -> Path:
        """Update presentation-only state without rewriting generated resume content."""
        folder = self.application_folder(slug)
        metadata_path = folder / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["photo_enabled"] = bool(photo_enabled)
        if template_name is not None:
            if template_name not in {"modern_sidebar", "ats_classic"}:
                raise ValueError("Unsupported resume layout")
            metadata["template_name"] = template_name
        if modern_photo_enabled is not None:
            metadata["modern_photo_enabled"] = modern_photo_enabled
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return folder

    def delete_application(self, slug: str) -> None:
        folder = self.application_folder(slug)
        metadata_path = folder / "metadata.json"
        draft_id = None
        try:
            draft_id = json.loads(metadata_path.read_text(encoding="utf-8")).get("draft_id")
        except (OSError, json.JSONDecodeError):
            pass
        shutil.rmtree(folder)
        if isinstance(draft_id, str) and re.fullmatch(r"[a-f0-9]{32}", draft_id):
            (self.drafts_dir / f"{draft_id}.json").unlink(missing_ok=True)

    def clear_history(self) -> int:
        slugs = [path.parent.name for path in self.generated_dir.glob("*/metadata.json")]
        removed = 0
        for slug in slugs:
            try:
                self.delete_application(slug)
                removed += 1
            except FileNotFoundError:
                continue
        return removed

    def history(self) -> list[dict]:
        rows = []
        for metadata_path in self.generated_dir.glob("*/metadata.json"):
            if metadata_path.parent.name.startswith('.'):
                continue
            try:
                item = json.loads(metadata_path.read_text(encoding="utf-8"))
                item["slug"] = metadata_path.parent.name
                item["has_pdf"] = (metadata_path.parent / "resume.pdf").exists()
                item["has_docx"] = (metadata_path.parent / "resume.docx").exists()
                rows.append(item)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(rows, key=lambda item: (item["date"], item["slug"]), reverse=True)

    def analysis_history(self) -> list[dict]:
        """Expose persisted requests and reports that have no generated application.

        Tasks already save the original job before contacting a provider. Reading
        them here also restores older unfinished work without migrating user data.
        """
        from app.services.task_manager import TaskKind, TaskRecord, TaskStatus

        exported = {row.get('draft_id') for row in self.history()}
        drafts, rows, represented = {}, [], set()
        for path in self.drafts_dir.glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{32}', path.stem) or path.stem in exported:
                continue
            try:
                payload = json.loads(path.read_text(encoding='utf-8'))
                job = JobRequest.model_validate(payload['job'])
                WorkflowResponse.model_validate(payload['response'])
                created = payload.get('created_at') or datetime.fromtimestamp(path.stat().st_mtime, timezone.utc).isoformat()
                drafts[path.stem] = (job, created)
            except (OSError, ValueError, KeyError, TypeError):
                continue
        for path in (self.data_dir / 'tasks').glob('*.json'):
            if not re.fullmatch(r'[a-f0-9]{32}', path.stem):
                continue
            try:
                task = TaskRecord.model_validate_json(path.read_text(encoding='utf-8'))
                if task.kind != TaskKind.TAILOR or task.task_id != path.stem:
                    continue
                job = JobRequest.model_validate(task.payload.get('job'))
                draft_id = (task.result or {}).get('draft_id')
                if isinstance(draft_id, str) and draft_id in exported:
                    continue
                has_report = isinstance(draft_id, str) and draft_id in drafts
                # Deleting a generated CV also deletes its draft. Do not revive
                # its completed task as an unfinished analysis afterward.
                if task.status == TaskStatus.COMPLETED and not has_report:
                    continue
                if has_report:
                    if draft_id in represented:
                        continue
                    represented.add(draft_id)
                rows.append({
                    'company': job.company, 'role': job.role, 'job_url': str(job.job_url) if job.job_url else None,
                    'date': task.created_at, 'status': 'report_ready' if has_report else task.status.value,
                    'interrupted': task.stage == 'Interrupted',
                    'view_url': f'/analysis/{draft_id}' if has_report else f'/tasks/{task.task_id}/view',
                    'edit_url': f'/?from_task={task.task_id}',
                })
            except (OSError, ValueError, TypeError):
                continue
        for draft_id, (job, created) in drafts.items():
            if draft_id in represented:
                continue
            rows.append({
                'company': job.company, 'role': job.role, 'job_url': str(job.job_url) if job.job_url else None,
                'date': created, 'status': 'report_ready', 'interrupted': False,
                'view_url': f'/analysis/{draft_id}', 'edit_url': f'/?from_draft={draft_id}',
            })
        return sorted(rows, key=lambda row: (row['date'], row['view_url']), reverse=True)

    def load_pre_fit_resume(self, slug: str) -> TailoredResume | None:
        folder = self.application_folder(slug)
        pre_fit_path = folder / "pre_fit_resume.json"
        if pre_fit_path.is_file():
            try:
                return TailoredResume.model_validate_json(pre_fit_path.read_text(encoding="utf-8"))
            except Exception:
                return None
        return None

    def artifact(self, slug: str, filename: str) -> Path:
        if filename not in {"resume.pdf", "resume.docx"}:
            raise FileNotFoundError
        path = (self.application_folder(slug) / filename).resolve()
        if path.parent != self.application_folder(slug).resolve() or not path.is_file():
            raise FileNotFoundError
        return path


def compute_pre_fit_diff(pre_fit: TailoredResume | None, fitted: TailoredResume) -> dict:
    """Compute detailed differences between the model proposal (pre-fit) and layout-fitted resume."""
    if not pre_fit:
        return {
            "trimmed_skills": [],
            "trimmed_bullets": [],
            "shortened_bullets": [],
            "trimmed_projects": [],
            "summary_shortened": False,
            "original_summary_len": len(fitted.professional_summary),
            "fitted_summary_len": len(fitted.professional_summary),
            "total_items": 0,
        }

    # 1. Trimmed skills
    fitted_skills_set = set(fitted.core_skills)
    trimmed_skills = [skill for skill in pre_fit.core_skills if skill not in fitted_skills_set]

    # 2. Trimmed projects
    fitted_project_names = {p.name.casefold() for p in fitted.projects}
    trimmed_projects = [p.name for p in pre_fit.projects if p.name.casefold() not in fitted_project_names]

    # 3. Bullets differences
    trimmed_bullets = []
    shortened_bullets = []
    fitted_exp_map = {item.company.casefold(): item for item in fitted.experience}

    for orig_item in pre_fit.experience:
        fitted_item = fitted_exp_map.get(orig_item.company.casefold())
        if not fitted_item:
            for b in orig_item.bullets:
                trimmed_bullets.append({"company": orig_item.company, "text": b.text})
            continue

        fitted_texts = [b.text for b in fitted_item.bullets]
        for orig_b in orig_item.bullets:
            # Check exact match
            if orig_b.text in fitted_texts:
                continue
            # Check if shortened version exists
            match_found = False
            for f_text in fitted_texts:
                if f_text and (f_text in orig_b.text or orig_b.text.startswith(f_text[:40])):
                    shortened_bullets.append({
                        "company": orig_item.company,
                        "original": orig_b.text,
                        "fitted": f_text,
                    })
                    match_found = True
                    break
            if not match_found:
                trimmed_bullets.append({"company": orig_item.company, "text": orig_b.text})

    # 4. Summary shortening
    orig_sum_len = len(pre_fit.professional_summary)
    fit_sum_len = len(fitted.professional_summary)
    summary_shortened = orig_sum_len > fit_sum_len and pre_fit.professional_summary != fitted.professional_summary

    total_items = (
        len(trimmed_skills)
        + len(trimmed_projects)
        + len(trimmed_bullets)
        + len(shortened_bullets)
        + (1 if summary_shortened else 0)
    )

    return {
        "trimmed_skills": trimmed_skills,
        "trimmed_projects": trimmed_projects,
        "trimmed_bullets": trimmed_bullets,
        "shortened_bullets": shortened_bullets,
        "summary_shortened": summary_shortened,
        "original_summary": pre_fit.professional_summary,
        "fitted_summary": fitted.professional_summary,
        "original_summary_len": orig_sum_len,
        "fitted_summary_len": fit_sum_len,
        "total_items": total_items,
    }
