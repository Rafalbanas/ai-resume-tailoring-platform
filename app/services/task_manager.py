import asyncio
import hashlib
import logging
import re
import time
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.job import JobRequest
from app.services.ai_provider import AIProviderError, GeminiAuthError
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_validator import FactValidator

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class TaskKind(str, Enum):
    TAILOR = "tailor"
    COMPARE = "compare"


class TaskRecord(BaseModel):
    task_id: str
    kind: TaskKind
    idempotency_key: str
    status: TaskStatus = TaskStatus.QUEUED
    stage: str = "Waiting in queue..."
    progress_percent: int = 0
    created_at: str
    started_at: str | None = None
    completed_at: str | None = None
    queued_duration_seconds: float | None = None
    execution_duration_seconds: float | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: str | None = None
    error_status_code: int | None = None


def compute_idempotency_key(kind: str, **kwargs) -> str:
    raw = f"{kind}:" + ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TaskManager:
    """Manages background task execution, persistence, idempotency, and recovery."""

    def __init__(self, data_dir: Path, budget_seconds: float = 900.0):
        self.tasks_dir = data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.budget_seconds = budget_seconds
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, task: TaskRecord) -> None:
        path = self._task_path(task.task_id)
        temp_path = path.with_suffix(".tmp")
        temp_path.write_text(task.model_dump_json(indent=2), encoding="utf-8")
        temp_path.replace(path)

    def get_task(self, task_id: str) -> TaskRecord | None:
        if not re.fullmatch(r"[a-f0-9]{32}", task_id):
            return None
        path = self._task_path(task_id)
        if not path.is_file():
            return None
        try:
            return TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.error("Failed to read task %s (%s)", task_id, type(exc).__name__)
            return None

    async def recover_on_startup(self) -> int:
        """Finds any tasks left as running or queued on startup and marks them failed."""
        recovered = 0
        now = datetime.now(timezone.utc).isoformat()
        for path in self.tasks_dir.glob("*.json"):
            try:
                task = TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if task.status in (TaskStatus.RUNNING, TaskStatus.QUEUED):
                    task.status = TaskStatus.FAILED
                    task.stage = "Interrupted"
                    task.completed_at = now
                    task.error = "Task interrupted by an application restart. Please retry."
                    task.error_status_code = 500
                    self._save_task(task)
                    recovered += 1
            except Exception as exc:
                logger.warning("Invalid task file during recovery (%s)", type(exc).__name__)
        if recovered > 0:
            logger.info("Task recovery on startup: cleaned up %d orphaned task(s)", recovered)
        return recovered

    def find_active_by_idempotency_key(self, key: str, max_age_seconds: float = 900.0) -> TaskRecord | None:
        now = datetime.now(timezone.utc)
        for path in self.tasks_dir.glob("*.json"):
            try:
                task = TaskRecord.model_validate_json(path.read_text(encoding="utf-8"))
                if task.idempotency_key == key and task.status in (TaskStatus.QUEUED, TaskStatus.RUNNING):
                    created_dt = datetime.fromisoformat(task.created_at)
                    if (now - created_dt).total_seconds() <= max_age_seconds:
                        return task
            except Exception:
                continue
        return None

    def create_task(self, kind: TaskKind, payload: dict[str, Any], idempotency_key: str) -> TaskRecord:
        task_id = uuid4().hex
        task = TaskRecord(
            task_id=task_id,
            kind=kind,
            idempotency_key=idempotency_key,
            status=TaskStatus.QUEUED,
            stage="Waiting in queue...",
            progress_percent=5,
            created_at=datetime.now(timezone.utc).isoformat(),
            payload=payload,
        )
        self._save_task(task)
        self._queue.put_nowait(task_id)
        logger.info("Enqueued task %s (%s, idempotency=%s)", task_id, kind.value, idempotency_key[:12])
        return task

    def update_task_progress(self, task_id: str, stage: str, progress_percent: int) -> None:
        task = self.get_task(task_id)
        if task:
            task.stage = stage
            task.progress_percent = progress_percent
            self._save_task(task)

    def start_worker(self, app_state: Any) -> None:
        if self._worker_task is None or self._worker_task.done():
            self._stop_event.clear()
            self._worker_task = asyncio.create_task(self._worker_loop(app_state))
            logger.info("Background task worker started")

    def stop_worker(self) -> None:
        self._stop_event.set()
        if self._worker_task and not self._worker_task.done():
            self._worker_task.cancel()
            logger.info("Background task worker stopped")

    async def _worker_loop(self, app_state: Any) -> None:
        while not self._stop_event.is_set():
            try:
                task_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except (TimeoutError, asyncio.TimeoutError):
                continue
            except asyncio.CancelledError:
                break

            task = self.get_task(task_id)
            if not task or task.status != TaskStatus.QUEUED:
                self._queue.task_done()
                continue

            started_dt = datetime.now(timezone.utc)
            created_dt = datetime.fromisoformat(task.created_at)
            queued_duration = max(0.0, (started_dt - created_dt).total_seconds())

            task.status = TaskStatus.RUNNING
            task.started_at = started_dt.isoformat()
            task.queued_duration_seconds = round(queued_duration, 2)
            task.stage = "Starting generation..."
            task.progress_percent = 10
            self._save_task(task)

            wall_start = time.perf_counter()

            try:
                await asyncio.wait_for(
                    self._execute_task(task, app_state),
                    timeout=self.budget_seconds,
                )
            except (TimeoutError, asyncio.TimeoutError):
                exec_duration = time.perf_counter() - wall_start
                task = self.get_task(task_id) or task
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.execution_duration_seconds = round(exec_duration, 2)
                task.stage = "Time limit exceeded"
                task.error = f"Task execution budget exceeded ({int(self.budget_seconds)} s)."
                task.error_status_code = 504
                self._save_task(task)
                logger.error("Task %s timed out after %.1fs", task_id, exec_duration)
            except GeminiAuthError as exc:
                exec_duration = time.perf_counter() - wall_start
                task = self.get_task(task_id) or task
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.execution_duration_seconds = round(exec_duration, 2)
                task.stage = "Authentication failed"
                task.error = str(exc)
                task.error_status_code = 401
                self._save_task(task)
                logger.warning("Task %s auth error: %s", task_id, exc)
            except AIProviderError as exc:
                exec_duration = time.perf_counter() - wall_start
                task = self.get_task(task_id) or task
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.execution_duration_seconds = round(exec_duration, 2)
                task.stage = "AI generation failed"
                task.error = str(exc)
                task.error_status_code = 502
                self._save_task(task)
                logger.warning("Task %s provider error: %s", task_id, exc)
            except Exception as exc:
                exec_duration = time.perf_counter() - wall_start
                task = self.get_task(task_id) or task
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.execution_duration_seconds = round(exec_duration, 2)
                task.stage = "Unexpected error"
                task.error = "Processing failed. The task was not completed."
                task.error_status_code = 500
                self._save_task(task)
                logger.error("Task %s failed unexpectedly (%s)", task_id, type(exc).__name__)
            finally:
                self._queue.task_done()

    async def _execute_task(self, task: TaskRecord, app_state: Any) -> None:
        if task.kind == TaskKind.TAILOR:
            await self._execute_tailor(task, app_state)
        elif task.kind == TaskKind.COMPARE:
            await self._execute_compare(task, app_state)
        else:
            raise ValueError(f"Unknown task kind {task.kind}")

    async def _execute_tailor(self, task: TaskRecord, app_state: Any) -> None:
        job = JobRequest.model_validate(task.payload["job"])
        llm_provider = task.payload.get("llm_provider", "auto")
        wall_start = time.perf_counter()

        def on_stage_cb(stage_name: str) -> None:
            self.update_task_progress(task.task_id, stage=stage_name, progress_percent=0)

        on_stage_cb("Starting generation...")

        try:
            response = await app_state.provider.tailor(
                job, app_state.profile, requested_provider=llm_provider, on_stage=on_stage_cb
            )
        except TypeError:
            try:
                response = await app_state.provider.tailor(
                    job, app_state.profile, requested_provider=llm_provider
                )
            except TypeError:
                response = await app_state.provider.tailor(job, app_state.profile)

        on_stage_cb("Validating Truth Lock...")

        response.analysis = AnalysisValidator(app_state.profile, app_state.skills_bank).validate(
            response.analysis, f"{job.role}\n{job.job_description}"
        )

        on_stage_cb("Saving application draft...")

        draft_id = app_state.storage.save_draft(job, response)
        exec_duration = time.perf_counter() - wall_start
        duration_ms = int(exec_duration * 1000)

        if hasattr(app_state, "diagnostics"):
            app_state.diagnostics.record(
                company=job.company,
                role=job.role,
                requested_provider=llm_provider,
                provider_used=getattr(response, "provider_used", "unknown"),
                model_used=getattr(response, "model_used", "unknown"),
                fallback_occurred=getattr(response, "fallback_used", False),
                fallback_reason=getattr(response, "fallback_reason", None),
                status="fallback" if getattr(response, "fallback_used", False) else "success",
                duration_ms=duration_ms,
                match_level=response.analysis.match_level,
                recommendation=response.analysis.recommendation,
            )

        task = self.get_task(task.task_id) or task
        task.status = TaskStatus.COMPLETED
        task.stage = "Draft ready for review" if response.analysis.is_reliable else "Analysis requires review"
        task.progress_percent = 100
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.execution_duration_seconds = round(exec_duration, 2)
        task.result = {
            "draft_id": draft_id,
            "redirect_url": f"/analysis/{draft_id}",
            "provider_used": getattr(response, "provider_used", "unknown"),
            "model_used": getattr(response, "model_used", "unknown"),
            "fallback_used": getattr(response, "fallback_used", False),
            "fallback_reason": getattr(response, "fallback_reason", None),
        }
        self._save_task(task)
        logger.info("Task %s (tailor) completed in %.2fs -> draft %s", task.task_id, exec_duration, draft_id)

    async def _execute_compare(self, task: TaskRecord, app_state: Any) -> None:
        job = JobRequest.model_validate(task.payload["job"])
        wall_start = time.perf_counter()

        available_providers = getattr(app_state, "providers", {})
        provider_names = ["ollama", "gemini"]
        if getattr(app_state.settings, "ai_provider", "") == "mock" or "mock" in available_providers:
            if "mock" not in provider_names:
                provider_names.append("mock")

        results: dict[str, dict] = {}
        total = len(provider_names)

        for idx, name in enumerate(provider_names):
            pct = 20 + int((idx / total) * 60)
            self.update_task_progress(
                task.task_id,
                stage=f"Testing model {name.capitalize()}...",
                progress_percent=pct,
            )

            provider = available_providers.get(name)
            if not provider:
                results[name] = {"ok": False, "model": name, "error": f"Provider '{name}' is not configured."}
                continue

            if name == "gemini" and getattr(provider, "api_key", None) == "":
                results[name] = {
                    "ok": False,
                    "model": getattr(provider, "model", "gemini-3.1-flash-lite"),
                    "error": "Gemini API key is not configured. Set GEMINI_API_KEY to test Gemini.",
                }
                continue

            step_start = time.perf_counter()
            try:
                resp = await provider.tailor(job, app_state.profile)
                resp.analysis = AnalysisValidator(app_state.profile, app_state.skills_bank).validate(
                    resp.analysis, f"{job.role}\n{job.job_description}"
                )
                val = FactValidator(app_state.profile, app_state.skills_bank).validate(resp.resume, job)
                results[name] = {
                    "ok": True,
                    "duration_ms": int((time.perf_counter() - step_start) * 1000),
                    "model": getattr(provider, "model", name),
                    "analysis": resp.analysis.model_dump(mode="json"),
                    "resume": val.resume.model_dump(mode="json"),
                    "truth_warnings": val.warnings,
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "duration_ms": int((time.perf_counter() - step_start) * 1000),
                    "model": getattr(provider, "model", name),
                    "error": str(exc),
                }

        self.update_task_progress(
            task.task_id,
            stage="Preparing results...",
            progress_percent=90,
        )

        exec_duration = time.perf_counter() - wall_start
        task = self.get_task(task.task_id) or task
        task.status = TaskStatus.COMPLETED
        task.stage = "Completed successfully"
        task.progress_percent = 100
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.execution_duration_seconds = round(exec_duration, 2)
        task.result = {
            "job": job.model_dump(mode="json"),
            "results": results,
            "redirect_url": f"/compare?task_id={task.task_id}",
        }
        self._save_task(task)
        logger.info("Task %s (compare) completed in %.2fs", task.task_id, exec_duration)
