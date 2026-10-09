import json
import re
import shutil
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse


def safe_filename(value: str, fallback: str = "item") -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode().lower()
    cleaned = re.sub(r"[^a-z0-9]+", "-", normalized).strip("-")
    return (cleaned[:80] or fallback).strip(".-")


class Storage:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        self.generated_dir = data_dir / "generated"
        self.drafts_dir = data_dir / ".drafts"
        self.generated_dir.mkdir(parents=True, exist_ok=True)
        self.drafts_dir.mkdir(parents=True, exist_ok=True)

    def save_draft(self, job: JobRequest, response: WorkflowResponse) -> str:
        draft_id = uuid4().hex
        payload = {"job": job.model_dump(mode="json"), "response": response.model_dump(mode="json")}
        (self.drafts_dir / f"{draft_id}.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return draft_id

    def load_draft(self, draft_id: str) -> tuple[JobRequest, WorkflowResponse]:
        if not re.fullmatch(r"[a-f0-9]{32}", draft_id):
            raise FileNotFoundError(draft_id)
        payload = json.loads((self.drafts_dir / f"{draft_id}.json").read_text(encoding="utf-8"))
        return JobRequest.model_validate(payload["job"]), WorkflowResponse.model_validate(payload["response"])

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
        metadata = {
            "company": job.company,
            "role": job.role,
            "job_url": str(job.job_url) if job.job_url else None,
            "date": date,
            "match_level": analysis.match_level,
            "recommendation": analysis.recommendation,
            "warnings": warnings,
            "generation_warnings": warnings,
            "truth_lock_warnings": truth_lock_warnings if truth_lock_warnings is not None else warnings,
            "layout_warnings": layout_warnings or [],
            "layout_guide": layout_guide or {},
            "draft_id": draft_id,
            "template_name": template_name,
            "photo_enabled": bool(photo_enabled),
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return slug, folder

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
    ) -> Path:
        folder = self.application_folder(slug)
        (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        metadata_path = folder / "metadata.json"
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata["warnings"] = warnings
        if truth_lock_warnings is not None:
            metadata["truth_lock_warnings"] = truth_lock_warnings
        if layout_warnings is not None:
            metadata["layout_warnings"] = layout_warnings
        if template_name is not None:
            metadata["template_name"] = template_name
        if photo_enabled is not None:
            metadata["photo_enabled"] = bool(photo_enabled)
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
            try:
                item = json.loads(metadata_path.read_text(encoding="utf-8"))
                item["slug"] = metadata_path.parent.name
                item["has_pdf"] = (metadata_path.parent / "resume.pdf").exists()
                item["has_docx"] = (metadata_path.parent / "resume.docx").exists()
                rows.append(item)
            except (OSError, json.JSONDecodeError):
                continue
        return sorted(rows, key=lambda item: (item["date"], item["slug"]), reverse=True)

    def artifact(self, slug: str, filename: str) -> Path:
        if filename not in {"resume.pdf", "resume.docx"}:
            raise FileNotFoundError
        path = (self.application_folder(slug) / filename).resolve()
        if not path.is_file():
            raise FileNotFoundError
        return path
