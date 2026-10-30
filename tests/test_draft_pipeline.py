from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.storage import DraftDataError, Storage
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


@pytest.mark.asyncio
@pytest.mark.parametrize("invalid", [False, True])
async def test_task_only_completes_with_readable_draft(tmp_path, resume_payload, monkeypatch, invalid):
    job = JobRequest(company="Acme", role="Engineer", job_description="A complete job description for testing.")
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation="RETRY", match_level="UNRELIABLE")
    analysis.reasoning_summary = "x" * 3062
    response = WorkflowResponse(analysis=analysis, resume=TailoredResume.model_validate(resume_payload))
    if invalid:
        response.resume.headline = "x" * 141
    monkeypatch.setattr("app.services.task_manager.AnalysisValidator",
                        lambda *args: SimpleNamespace(validate=lambda analysis, _: analysis))
    state = SimpleNamespace(provider=SimpleNamespace(tailor=AsyncMock(return_value=response)),
                            profile=None, skills_bank=None, storage=Storage(tmp_path))
    manager = TaskManager(tmp_path, budget_seconds=5)
    task = manager.create_task(TaskKind.TAILOR, payload={"job": job.model_dump(mode="json")},
                               idempotency_key="test")
    if invalid:
        with pytest.raises(DraftDataError):
            await manager._execute_tailor(task, state)
        assert manager.get_task(task.task_id).status != TaskStatus.COMPLETED
        assert not list(state.storage.drafts_dir.glob("*.json"))
    else:
        await manager._execute_tailor(task, state)
        finished = manager.get_task(task.task_id)
        assert finished.status == TaskStatus.COMPLETED
        restored_job, restored = state.storage.load_draft(finished.result["draft_id"])
        assert restored_job == job
        assert len(restored.analysis.reasoning_summary) == 2000
