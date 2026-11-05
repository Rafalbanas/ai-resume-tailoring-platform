"""Fifty offers remain sequential and bounded; failures do not stop later offers."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.models.job import JobExtraction
from app.services.batch import now, run_batch
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


@pytest.mark.parametrize('failed_index', [None, 17])
async def test_fifty_offer_batch_keeps_every_item_and_isolates_failure(tmp_path, monkeypatch, failed_index):
    manager = TaskManager(tmp_path)
    urls = [f'https://example.com/offer-{index}' for index in range(50)]
    parent = manager.create_task(TaskKind.BATCH, {'batch': {'urls': urls, 'export': False, 'llm_provider': 'mock'}}, 'synthetic-large-batch')
    parent.started_at = now()
    parent.status = TaskStatus.RUNNING
    manager._save_task(parent)
    extracted = JobExtraction(company='Synthetic', role='Support', source=urls[0], extraction_method='html',
                              job_description='Requirements\nSupport Python and Linux workflows.')
    state = SimpleNamespace(resource_budget=SimpleNamespace(check_disk=lambda: None),
                            job_extractor=SimpleNamespace(extract=AsyncMock(return_value=extracted)))
    visited = []
    async def execute(child, state):
        index = len(visited)
        visited.append(child.payload['job']['job_url'])
        if index == failed_index:
            raise ValueError('Synthetic per-offer failure')
        child.status = TaskStatus.COMPLETED
        child.result = {'draft_id': child.task_id, 'provider_used': 'mock', 'model_used': 'synthetic', 'fallback_used': False}
        manager._save_task(child)
    monkeypatch.setattr(manager, '_execute_task', execute)
    await run_batch(manager, parent, state)
    saved = manager.get_task(parent.task_id)
    assert saved.status == TaskStatus.COMPLETED
    assert visited == urls
    assert state.job_extractor.extract.await_count == 50
    items = saved.result['items']
    assert len(items) == 50
    assert [item['url'] for item in items] == urls
    assert sum(item['status'] == 'failed' for item in items) == (failed_index is not None)
    assert sum(item['status'] == 'draft_ready' for item in items) == 50 - (failed_index is not None)
    assert items[-1]['status'] == 'draft_ready'
