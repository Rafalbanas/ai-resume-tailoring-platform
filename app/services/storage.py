import json
import re
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
        self, job: JobRequest, analysis: JobAnalysis, resume: TailoredResume, warnings: list[str]
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
        (folder / "analysis.json").write_text(analysis.model_dump_json(indent=2), encoding="utf-8")
        (folder / "resume.json").write_text(resume.model_dump_json(indent=2), encoding="utf-8")
        metadata = {
            "company": job.company,
            "role": job.role,
            "job_url": str(job.job_url) if job.job_url else None,
            "date": date,
            "match_level": analysis.match_level,
            "recommendation": analysis.recommendation,
            "warnings": warnings,
        }
        (folder / "metadata.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
        return slug, folder

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
        if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,240}", slug) or filename not in {"resume.pdf", "resume.docx"}:
            raise FileNotFoundError
        path = (self.generated_dir / slug / filename).resolve()
        if self.generated_dir.resolve() not in path.parents or not path.is_file():
            raise FileNotFoundError
        return path
