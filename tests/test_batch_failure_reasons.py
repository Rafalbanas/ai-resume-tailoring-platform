"""Per-offer errors expose a fixed category, never provider text or user data."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.job import JobExtraction
from app.services.ai_provider import AIProviderError
from app.services.batch import now, run_batch
from app.services.ollama_analysis import OllamaAnalysisError
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


@pytest.mark.parametrize('error,code', [
    (OllamaAnalysisError('coverage', 'PRIVATE SECRET'), 'analysis_validation'),
    (OllamaAnalysisError('evidence', 'PRIVATE SECRET'), 'analysis_validation'),
    (AIProviderError('PRIVATE SECRET'), 'provider_error'),
    (RuntimeError('PRIVATE SECRET'), None),
])
async def test_fixed_failure_reason_preserves_isolation_and_privacy(tmp_path, monkeypatch, error, code):
    manager = TaskManager(tmp_path)
    parent = manager.create_task(TaskKind.BATCH, {'batch': {'urls': ['https://example.com/a', 'https://example.com/b'],
                                                          'export': False}}, 'synthetic-failure')
    parent.started_at = now()
    parent.status = TaskStatus.RUNNING
    manager._save_task(parent)
    extracted = JobExtraction(company='Synthetic', role='Support', source='https://example.com/a',
                              extraction_method='html', job_description='Requirements\nKnowledge of Python')
    state = SimpleNamespace(resource_budget=SimpleNamespace(check_disk=lambda: None),
                            job_extractor=SimpleNamespace(extract=AsyncMock(return_value=extracted)))
    calls = []
    async def execute(child, state):
        calls.append(child.task_id)
        if len(calls) == 1:
            raise error
        child.status = TaskStatus.COMPLETED
        child.result = {'draft_id': child.task_id}
        manager._save_task(child)
    monkeypatch.setattr(manager, '_execute_task', execute)
    await run_batch(manager, parent, state)
    result = manager.get_task(parent.task_id)
    first, second = result.result['items']
    child = manager.get_task(first['task_id'])
    assert first['status'] == 'failed' and second['status'] == 'draft_ready'
    assert first.get('error_code') == code
    assert child.status == TaskStatus.FAILED
    assert child.error_status_code == (502 if code else None)
    assert child.error == first['error']
    assert 'PRIVATE' not in first['error'] and 'SECRET' not in child.error
    assert result.status == TaskStatus.COMPLETED and len(calls) == 2
