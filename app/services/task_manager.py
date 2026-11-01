import asyncio
import fcntl
import hashlib
import json
import logging
import os
import re
import tempfile
import time
from contextlib import contextmanager
from copy import copy
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import HTTPException
from pydantic import BaseModel, Field

from app.models.job import JobAnalysis, JobRequest
from app.services.ai_provider import AIProviderError, GeminiAuthError
from app.services.analysis_validator import AnalysisValidator
from app.services.comparison_capture import capture_comparison
from app.services.fact_validator import FactValidator

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    REJECTED = "rejected"


class TaskKind(str, Enum):
    TAILOR = "tailor"
    COMPARE = "compare"
    CUSTOM_EDIT = "custom_edit"
    BENCHMARK = "benchmark"
    EXPORT = "export"


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
    token_usage: dict[str, Any] = Field(default_factory=dict)
    keep_history: bool = False


def compute_idempotency_key(kind: str, **kwargs) -> str:
    raw = f"{kind}:" + ":".join(f"{k}={v}" for k, v in sorted(kwargs.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class TaskManager:
    """Manages background task execution, persistence, idempotency, and recovery."""

    def __init__(self, data_dir: Path, budget_seconds: float = 900.0, max_pending: int = 4, auto_delete_history: bool = False):
        self.tasks_dir = data_dir / "tasks"
        self.tasks_dir.mkdir(parents=True, exist_ok=True)
        self.budget_seconds = budget_seconds
        self.max_pending = max_pending
        self.auto_delete_history = auto_delete_history
        self._queue: asyncio.Queue[str] = asyncio.Queue(maxsize=max_pending)
        self._worker_task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._pending_task_ids: dict[str, None] = {}
        self._active_task_id: str | None = None
        self._pause_path = data_dir / '.queue-control.json'
        self._paused = False
        if self._pause_path.exists():
            try:
                paused = json.loads(self._pause_path.read_text())['paused']
                if not isinstance(paused, bool):
                    raise ValueError('Invalid queue pause state')
                self._paused = paused
            except (OSError, ValueError, KeyError, TypeError):
                self._paused = True
                logger.warning('Invalid queue control state; queue paused until explicitly resumed')

    def _task_path(self, task_id: str) -> Path:
        return self.tasks_dir / f"{task_id}.json"

    def _save_task(self, task: TaskRecord) -> None:
        path = self._task_path(task.task_id)
        temp_path = path.with_suffix(".tmp")
        serialized = task.model_dump_json(indent=2)
        if len(serialized.encode()) > 8 * 1024 * 1024:
            raise ValueError('Task result exceeds the storage limit')
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(serialized)
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

    def activity_for(self, task: TaskRecord | None = None) -> dict[str, Any]:
        """Read-only account-local worker snapshot; never scan another account.

        Read only the small live queue, not every historical CV on every poll.
        Position is among waiting requests (1 means next), not an ETA.
        """
        activity = {"queue_position": None, "queued_ahead": 0, "running_tasks": [],
                    "queued_tasks": [], "paused": self._paused}
        pending = []
        for task_id in list(self._pending_task_ids):
            queued = self.get_task(task_id)
            if queued and queued.status == TaskStatus.QUEUED:
                pending.append(task_id)
                activity['queued_tasks'].append(self._activity_row(queued))
        if task and task.status == TaskStatus.QUEUED and task.task_id in pending:
            position = pending.index(task.task_id) + 1
            activity['queue_position'] = position
            activity['queued_ahead'] = position - 1
        active_id = self._active_task_id
        if active_id:
            current = self.get_task(active_id)
            if current and current.status == TaskStatus.RUNNING:
                activity['running_tasks'].append(self._activity_row(current))
        return activity

    @staticmethod
    def _activity_row(task):
        job = task.payload.get('job') or {}
        if not isinstance(job, dict):
            job = {}
        if task.kind == TaskKind.BENCHMARK:
            job = {'company': 'Benchmark', 'role': f"{len(task.payload.get('benchmark', {}).get('urls', []))} offers · full / cleaned"}
        return {'task_id': task.task_id, 'company': str(job.get('company', '')),
                'role': str(job.get('role', '')), 'kind': task.kind.value, 'stage': task.stage,
                'started_at': task.started_at, 'model': task.token_usage.get('model')}

    def set_paused(self, paused: bool) -> None:
        if not isinstance(paused, bool):
            raise ValueError('Invalid queue pause state')
        descriptor, temporary = tempfile.mkstemp(dir=self.tasks_dir.parent, prefix='.queue-control-')
        try:
            with os.fdopen(descriptor, 'w') as handle:
                json.dump({'paused': paused}, handle)
            os.replace(temporary, self._pause_path)
            self._paused = paused
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def reject_queued(self, task_id: str) -> TaskRecord:
        task = self.get_task(task_id)
        if task is None:
            raise HTTPException(404, 'Task not found')
        if task.status != TaskStatus.QUEUED or task_id == self._active_task_id:
            raise HTTPException(409, 'Only waiting tasks can be rejected. Active tasks finish normally.')
        task.status = TaskStatus.REJECTED
        task.stage = 'Rejected before execution — history kept'
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.keep_history = True
        self._save_task(task)
        self._pending_task_ids.pop(task_id, None)
        # Compact using public Queue methods, preserving FIFO and join() counts.
        # Reinsert retained entries BEFORE task_done(), so join cannot wake early.
        retained, drained = [], 0
        while True:
            try:
                queued_id = self._queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            drained += 1
            if queued_id != task_id:
                retained.append(queued_id)
        for queued_id in retained:
            self._queue.put_nowait(queued_id)
        for _ in range(drained):
            self._queue.task_done()
        return task

    def retain_history(self, task: TaskRecord) -> None:
        task.keep_history = True
        self._save_task(task)

    def delete_inactive_entry(self, task_id: str) -> None:
        task = self.get_task(task_id)
        if task is None:
            raise HTTPException(404, 'Task not found')
        if task_id == self._active_task_id or task.status not in {TaskStatus.REJECTED, TaskStatus.FAILED} or task.result is not None:
            raise HTTPException(409, 'Only rejected or failed entries without saved results may be deleted here.')
        self._task_path(task_id).unlink()

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

    def find_by_idempotency_key(self, key: str) -> TaskRecord | None:
        for path in self.tasks_dir.glob('*.json'):
            task = self.get_task(path.stem)
            if task and task.idempotency_key == key:
                return task
        return None

    @contextmanager
    def _admission(self):
        descriptor = os.open(self.tasks_dir / '.admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            active, completed = 0, []
            for path in self.tasks_dir.glob('*.json'):
                task = self.get_task(path.stem)
                if task is None:
                    continue
                if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING}:
                    active += 1
                elif self.auto_delete_history and not task.keep_history:
                    completed.append((task.created_at, task.task_id, (task.result or {}).get('draft_id')))
            if active >= self.max_pending or self._queue.full():
                raise HTTPException(429, 'The task queue is full. Wait for an existing task to finish.')
            # Cleanup is opt-in; otherwise keep every finished task and draft.
            # Retain only compact metadata while scanning; never hold every
            # historical model payload in memory at once.
            completed.sort()
            stale = completed[:max(0, len(completed) - (99 - active))]
            linked = set()
            if stale:
                for path in (self.tasks_dir.parent / 'generated').glob('*/metadata.json'):
                    try:
                        linked.add(json.loads(path.read_text()).get('draft_id'))
                    except (ValueError, OSError):
                        pass
            for _, task_id, draft in stale:
                if isinstance(draft, str) and re.fullmatch(r'[a-f0-9]{32}', draft) and draft not in linked:
                    (self.tasks_dir.parent / '.drafts' / (draft + '.json')).unlink(missing_ok=True)
                self._task_path(task_id).unlink(missing_ok=True)
            yield
        finally:
            os.close(descriptor)

    def create_task(self, kind: TaskKind, payload: dict[str, Any], idempotency_key: str) -> TaskRecord:
        with self._admission():
            return self._create_task(kind, payload, idempotency_key)

    def _create_task(self, kind: TaskKind, payload: dict[str, Any], idempotency_key: str) -> TaskRecord:
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
        self._pending_task_ids[task_id] = None
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
                while self._paused:
                    await asyncio.sleep(.25)
                task_id = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except (TimeoutError, asyncio.TimeoutError):
                continue
            except asyncio.CancelledError:
                break

            try:
                # Pause may have been requested while queue.get() was waiting.
                while self._paused:
                    await asyncio.sleep(.25)
            except asyncio.CancelledError:
                self._queue.task_done()
                break

            task = self.get_task(task_id)
            self._pending_task_ids.pop(task_id, None)
            if not task or task.status != TaskStatus.QUEUED:
                self._queue.task_done()
                continue

            started_dt = datetime.now(timezone.utc)
            created_dt = datetime.fromisoformat(task.created_at)
            queued_duration = max(0.0, (started_dt - created_dt).total_seconds())

            task.status = TaskStatus.RUNNING
            self._active_task_id = task_id
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
            except HTTPException as exc:
                task = self.get_task(task_id) or task
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.now(timezone.utc).isoformat()
                task.execution_duration_seconds = round(time.perf_counter() - wall_start, 2)
                task.stage = 'Request validation failed'
                task.error = str(exc.detail)
                task.error_status_code = exc.status_code
                self._save_task(task)
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
                self._active_task_id = None
                self._queue.task_done()

    async def _execute_task(self, task: TaskRecord, app_state: Any) -> None:
        from app.services.token_progress import track_tokens
        def update(usage):
            current = self.get_task(task.task_id) or task
            current.token_usage = usage
            self._save_task(current)
        with track_tokens(update):
            await self._execute_task_with_usage(task, app_state)

    async def _execute_task_with_usage(self, task: TaskRecord, app_state: Any) -> None:
        if task.kind == TaskKind.TAILOR:
            await self._execute_tailor(task, app_state)
        elif task.kind == TaskKind.COMPARE:
            await self._execute_compare(task, app_state)
        elif task.kind == TaskKind.CUSTOM_EDIT:
            await self._execute_custom_edit(task, app_state)
        elif task.kind == TaskKind.BENCHMARK:
            await self._execute_benchmark(task, app_state)
        elif task.kind == TaskKind.EXPORT:
            await self._execute_export(task, app_state)
        else:
            raise ValueError(f"Unknown task kind {task.kind}")

    async def _execute_export(self, task, app_state):
        from app.services.draft_export import export_draft
        self.update_task_progress(task.task_id, 'Preparing PDF and DOCX — you can safely refresh this status page', 20)
        # Match the web mutation boundary: editors/settings must not race saved
        # artifacts while an export has moved out of the HTTP request lifespan.
        async with app_state.resource_budget.mutation_slots:
            slug = await export_draft(app_state, task.payload['draft_id'], **task.payload['export_options'])
        current = self.get_task(task.task_id) or task
        current.status = TaskStatus.COMPLETED
        current.stage = 'PDF and DOCX ready'
        current.progress_percent = 100
        current.completed_at = datetime.now(timezone.utc).isoformat()
        current.execution_duration_seconds = round((datetime.now(timezone.utc) - datetime.fromisoformat(current.started_at)).total_seconds(), 2)
        current.result = {'slug': slug, 'redirect_url': f'/preview/{slug}'}
        current.keep_history = True
        self._save_task(current)

    async def _execute_benchmark(self, task, app_state):
        from app.models.benchmark import BenchmarkRequest
        from app.services.benchmark import run_benchmark
        spec = BenchmarkRequest.model_validate(task.payload['benchmark'])

        def save_report(report):
            current = self.get_task(task.task_id) or task
            current.result = {'report': report, 'redirect_url': f'/api/v1/benchmarks/{task.task_id}'}
            self._save_task(current)

        await run_benchmark(spec, app_state,
                            lambda stage: self.update_task_progress(task.task_id, stage, 0), save_report)
        current = self.get_task(task.task_id) or task
        current.status = TaskStatus.COMPLETED
        current.stage = 'Benchmark finished — inspect per-variant validation before interpreting savings'
        current.progress_percent = 100
        current.completed_at = datetime.now(timezone.utc).isoformat()
        current.execution_duration_seconds = round((datetime.now(timezone.utc) - datetime.fromisoformat(current.started_at)).total_seconds(), 2)
        current.keep_history = True
        self._save_task(current)

    async def _execute_custom_edit(self, task, app_state):
        from app.services.cv_editor import CVEditorStore, apply_proposal, split_sections
        store = CVEditorStore(app_state.settings.data_dir)
        payload = task.payload
        try:
            doc = store.load(payload["cv_id"])
            store._check_revision(doc, payload["revision"])
        except OSError as exc:
            raise AIProviderError("This custom CV is no longer available. Return to the CV library.") from exc
        except ValueError as exc:
            raise AIProviderError("This CV changed or could not be read. Reload it before applying another prompt.") from exc
        if doc["pending"]:
            raise AIProviderError("Review or discard the previous proposal before applying another prompt.")
        sections = split_sections(doc["current"])
        self.update_task_progress(task.task_id, stage="Editing selected CV sections...", progress_percent=0)
        proposal = await app_state.provider.edit_cv({
            "stage": "edit_cv_sections", "sections": sections,
            "selected_sections": payload["selected_sections"], "instructions": payload["instructions"],
            "confirmed_additions": payload.get("confirmed_additions", ""),
        }, requested_provider=payload.get("llm_provider", "auto"))
        text = apply_proposal(sections, proposal, payload["selected_sections"], payload.get("confirmed_additions", ""))
        try:
            store.propose(doc["id"], payload["revision"], text, payload["instructions"], proposal.clarification)
        except (OSError, ValueError) as exc:
            raise AIProviderError("This CV changed while the AI was working. Your saved content was kept; reload and retry.") from exc
        task = self.get_task(task.task_id) or task
        task.status = TaskStatus.COMPLETED
        task.stage = "Changes ready for review"
        task.progress_percent = 100
        task.completed_at = datetime.now(timezone.utc).isoformat()
        task.result = {"redirect_url": f"/custom-cvs/{doc['id']}"}
        self._save_task(task)

    async def _execute_tailor(self, task: TaskRecord, app_state: Any) -> None:
        job = JobRequest.model_validate(task.payload["job"])
        if job.source_cv:
            try:
                _, source_resume, _, _ = app_state.storage.load_application(job.source_cv)
            except (OSError, ValueError) as exc:
                raise AIProviderError("The selected CV is unavailable. Choose another saved CV and retry.") from exc
            job._source_resume = source_resume.model_dump(mode="json")
        llm_provider = task.payload.get("llm_provider", "auto")
        provider = app_state.provider
        selected_model = task.payload.get("ollama_model")
        if ((selected_model or "ollama_context" in task.payload)
                and provider.resolve_chain(llm_provider)[0] == "ollama"):
            provider = copy(provider)
            provider.providers = dict(provider.providers)
            provider.providers["ollama"] = provider.providers["ollama"].with_selection(
                selected_model or provider.providers["ollama"].model, task.payload.get("ollama_context", 32768))
        wall_start = time.perf_counter()

        def on_stage_cb(stage_name: str) -> None:
            self.update_task_progress(task.task_id, stage=stage_name, progress_percent=0)

        on_stage_cb("Starting generation...")

        reused_analysis = task.payload.get('reuse_analysis')
        if reused_analysis is not None and job.workflow != "custom":
            reused_analysis = AnalysisValidator(app_state.profile, app_state.skills_bank).validate(
                JobAnalysis.model_validate(reused_analysis), f"{job.role}\n{job.job_description}")
            if not reused_analysis.is_reliable:
                raise AIProviderError('Saved analysis requires review. Analyze the offer again before generating.')

        try:
            if reused_analysis is not None:
                response = await provider.retailor(
                    job, app_state.profile, reused_analysis, requested_provider=llm_provider, on_stage=on_stage_cb)
            else:
                response = await provider.tailor(
                    job, app_state.profile, requested_provider=llm_provider, on_stage=on_stage_cb
                )
        except AIProviderError as exc:
            if hasattr(app_state, "diagnostics"):
                last_call = (getattr(exc, "call_metrics", []) or [{}])[-1]
                app_state.diagnostics.record(
                    company=job.company, role=job.role, requested_provider=llm_provider, task_id=task.task_id,
                    provider_used=last_call.get("provider", llm_provider), model_used=last_call.get("model", "unknown"),
                    fallback_occurred=bool(getattr(exc, "fallback_used", False)) or len({call.get("provider") for call in getattr(exc, "call_metrics", []) if call.get("provider")}) > 1,
                    status="error", duration_ms=int((time.perf_counter()-wall_start)*1000),
                    error_message=str(exc), call_metrics=getattr(exc, "call_metrics", []))
            raise
        except TypeError:
            if reused_analysis is not None:
                raise
            try:
                response = await provider.tailor(
                    job, app_state.profile, requested_provider=llm_provider
                )
            except TypeError:
                response = await provider.tailor(job, app_state.profile)

        on_stage_cb("Validating Truth Lock...")

        if job.workflow == "custom":
            from app.services.custom_cv import custom_analysis
            response.analysis = custom_analysis(job)
            checked = FactValidator(app_state.profile, app_state.skills_bank, response.analysis,
                                    review_key=app_state.settings.csrf_secret).validate(response.resume, job)
            response.resume = checked.resume
            response.summary_attestation = checked.resume.summary_attestation
        else:
            response.analysis = AnalysisValidator(app_state.profile, app_state.skills_bank).validate(
                response.analysis, f"{job.role}\n{job.job_description}"
            )

        on_stage_cb("Saving application draft...")

        response.token_usage = (self.get_task(task.task_id) or task).token_usage.copy()
        draft_id = app_state.storage.save_draft(job, response)
        exec_duration = time.perf_counter() - wall_start
        duration_ms = int(exec_duration * 1000)

        if hasattr(app_state, "diagnostics"):
            app_state.diagnostics.record(
                company=job.company,
                role=job.role,
                task_id=task.task_id,
                requested_provider=llm_provider,
                provider_used=getattr(response, "provider_used", "unknown"),
                model_used=getattr(response, "model_used", "unknown"),
                fallback_occurred=getattr(response, "fallback_used", False),
                fallback_reason=getattr(response, "fallback_reason", None),
                status=("review_required" if not response.analysis.is_reliable else
                        "fallback" if getattr(response, "fallback_used", False) else "success"),
                duration_ms=duration_ms,
                match_level=response.analysis.match_level,
                recommendation=response.analysis.recommendation,
                call_metrics=response.call_metrics,
                assessed_requirements=len(response.analysis.requirements),
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

            provider = copy(provider)
            if hasattr(provider, "max_retries"):
                provider.max_retries = 0
            step_start = time.perf_counter()
            try:
                with capture_comparison() as captured_calls:
                    resp = await provider.tailor(job, app_state.profile)
                model_analysis = resp.analysis._model_output
                model_resume = resp.resume.model_dump(mode="json")
                resp.analysis = AnalysisValidator(app_state.profile, app_state.skills_bank).validate(
                    resp.analysis, f"{job.role}\n{job.job_description}"
                )
                val = FactValidator(app_state.profile, app_state.skills_bank, resp.analysis,
                                    review_key=getattr(getattr(app_state, 'settings', None), 'csrf_secret', '')).validate(resp.resume, job)
                results[name] = {
                    "ok": True,
                    "duration_ms": int((time.perf_counter() - step_start) * 1000),
                    "model": getattr(provider, "model", name),
                    "analysis": resp.analysis.model_dump(mode="json"),
                    "resume": val.resume.model_dump(mode="json"),
                    "truth_warnings": val.warnings,
                    "model_analysis": model_analysis,
                    "model_resume": model_resume,
                    "summary_replaced": model_resume["professional_summary"] != val.resume.professional_summary,
                    "changed_resume_sections": [key for key, value in model_resume.items() if value != val.resume.model_dump(mode="json").get(key)],
                    "private_calls": captured_calls,
                    "input_fingerprints": {c["stage"]: {key: c[key] for key in ("payload_sha256", "system_prompt_sha256", "schema_sha256")} for c in captured_calls},
                    "call_metrics": [c["metrics"] for c in captured_calls],
                }
            except Exception as exc:
                results[name] = {
                    "ok": False,
                    "duration_ms": int((time.perf_counter() - step_start) * 1000),
                    "model": getattr(provider, "model", name),
                    "error": str(exc),
                    "private_calls": captured_calls,
                    "call_metrics": [c["metrics"] for c in captured_calls],
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
