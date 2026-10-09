import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

logger = logging.getLogger(__name__)


class DiagnosticLogStore:
    """Stores local diagnostic runs with FIFO retention (max 30 runs) and privacy safeguards."""

    def __init__(self, data_dir: Path, max_entries: int = 30):
        self.diagnostics_dir = data_dir / ".diagnostics"
        self.file_path = self.diagnostics_dir / "runs.json"
        self.max_entries = max_entries
        self.diagnostics_dir.mkdir(parents=True, exist_ok=True)

    def _load(self) -> list[dict]:
        if not self.file_path.exists():
            return []
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Failed to load diagnostic logs, resetting: %s", exc)
        return []

    def _save(self, runs: list[dict]) -> None:
        try:
            self.file_path.write_text(json.dumps(runs, indent=2), encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save diagnostic logs: %s", exc)

    def record(
        self,
        *,
        company: str,
        role: str,
        requested_provider: str,
        provider_used: str,
        model_used: str,
        fallback_occurred: bool,
        fallback_reason: str | None = None,
        status: str = "success",
        duration_ms: int = 0,
        match_level: str | None = None,
        recommendation: str | None = None,
        truth_lock_warning_count: int = 0,
        layout_warning_count: int = 0,
        error_message: str | None = None,
    ) -> dict:
        entry = {
            "id": uuid4().hex[:12],
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "company": (company or "Unknown")[:100],
            "role": (role or "Unknown")[:100],
            "requested_provider": requested_provider,
            "provider_used": provider_used,
            "model_used": model_used,
            "fallback_occurred": bool(fallback_occurred),
            "fallback_reason": fallback_reason,
            "status": status,
            "duration_ms": duration_ms,
            "match_level": match_level,
            "recommendation": recommendation,
            "truth_lock_warning_count": truth_lock_warning_count,
            "layout_warning_count": layout_warning_count,
            "error_message": (error_message or "")[:300] if error_message else None,
        }
        runs = self._load()
        runs.insert(0, entry)
        if len(runs) > self.max_entries:
            runs = runs[: self.max_entries]
        self._save(runs)
        return entry

    def list_runs(self, limit: int = 30) -> list[dict]:
        runs = self._load()
        return runs[:limit]

    def clear(self) -> None:
        self._save([])
