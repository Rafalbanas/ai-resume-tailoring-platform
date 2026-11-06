"""Budget admission is non-consuming and preserves idempotent lookups."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models.batch_api import BatchResponse
from app.models.job import JobExtraction
from app.services.ai_provider import DailyAIBudgetExceeded
from app.services.batch import now, run_batch
from app.services.task_manager import TaskKind, TaskManager, TaskStatus
from tests.test_batch_api import headers
from tests.test_queue_controls import login


@pytest.mark.parametrize('upload', [False, True])
def test_exhausted_budget_rejects_before_creating_or_fetching_a_batch(monkeypatch, upload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        budget = app.state.resource_budget
        budget.daily_calls = 1
        budget.charge()
        extractor = AsyncMock()
        monkeypatch.setattr(app.state.job_extractor, 'extract', extractor)
        before = set(app.state.task_manager.tasks_dir.glob('*.json'))
        if upload:
            response = client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', b'https://example.com/job')},
                                   headers=headers(client))
        else:
            response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job']}, headers=headers(client))
        assert response.status_code == 429
        assert '00:00 UTC' in response.json()['detail']
        assert int(response.headers['Retry-After']) > 0
        assert set(app.state.task_manager.tasks_dir.glob('*.json')) == before
        assert budget.remaining_ai_calls() == 0
        extractor.assert_not_called()


def test_idempotent_lookup_and_conflict_are_not_hidden_by_exhausted_budget(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        budget = app.state.resource_budget
        budget.daily_calls = 1
        body = {'urls': ['https://example.com/job']}
        created = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert created.status_code == 202
        assert budget.remaining_ai_calls() == 1
        budget.charge()
        repeated = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert repeated.status_code == 202
        assert repeated.json()['task_id'] == created.json()['task_id']
        conflict = client.post('/api/v1/batches', json={'urls': ['https://example.com/other']}, headers=headers(client))
        assert conflict.status_code == 409


def test_auth_and_csrf_still_precede_budget_details(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        app.state.resource_budget.daily_calls = 1
        app.state.resource_budget.charge()
        body = {'urls': ['https://example.com/job']}
        assert client.post('/api/v1/batches', json=body).status_code == 401
        login(client)
        assert client.post('/api/v1/batches', json=body).status_code == 403


def test_mid_batch_exhaustion_preserves_completed_items_and_does_not_fetch_remaining(tmp_path, monkeypatch):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.BATCH, {'batch': {'urls': [f'https://example.com/{i}' for i in range(4)],
                                                        'export': False}}, 'synthetic-quota')
    task.started_at = now()
    task.status = TaskStatus.RUNNING
    manager._save_task(task)
    extractor = AsyncMock(return_value=JobExtraction(company='Synthetic', role='Support', source='https://example.com/0',
                                                     extraction_method='html', job_description='Requirements\nKnowledge of Python'))
    state = SimpleNamespace(resource_budget=SimpleNamespace(check_disk=lambda: None), job_extractor=SimpleNamespace(extract=extractor))
    calls = []
    async def execute(child, state):
        calls.append(child.task_id)
        if len(calls) == 2:
            raise DailyAIBudgetExceeded()
        child.status = TaskStatus.COMPLETED
        child.result = {'draft_id': child.task_id}
        manager._save_task(child)
    monkeypatch.setattr(manager, '_execute_task', execute)
    asyncio.run(run_batch(manager, task, state))
    result = manager.get_task(task.task_id)
    items = result.result['items']
    assert result.status == TaskStatus.COMPLETED
    assert [i['status'] for i in items] == ['draft_ready', 'failed', 'failed', 'failed']
    assert len(calls) == extractor.await_count == 2
    assert all(i['error_code'] == 'daily_ai_budget' and i['retry_after_seconds'] > 0 for i in items[1:])
    assert not any(i.get('task_id') for i in items[2:])
    child = manager.get_task(items[1]['task_id'])
    assert child.status == TaskStatus.FAILED and child.error_status_code == 429
    response = BatchResponse.model_validate({'task_id': task.task_id, 'status': 'completed',
        'stage': result.stage, 'status_url': '/api/v1/batches/' + task.task_id, 'view_url': '/tasks/' + task.task_id,
        'result': result.result, 'error': None})
    assert response.result.items[2].error_code == 'daily_ai_budget'


@pytest.mark.asyncio
async def test_daily_limit_does_not_invoke_a_paid_or_other_fallback(profile, monkeypatch):
    from app.services.resilient_provider import ResilientAIProvider
    from tests.test_provider_fallback import FailingProvider, SucceedingProvider, job
    fallback = SucceedingProvider('gemini')
    forbidden = AsyncMock(side_effect=AssertionError('Daily quota must not trigger fallback'))
    monkeypatch.setattr(fallback, 'tailor', forbidden)
    provider = ResilientAIProvider({'ollama': FailingProvider('ollama', DailyAIBudgetExceeded()), 'gemini': fallback})
    with pytest.raises(DailyAIBudgetExceeded):
        await provider.tailor(job(), profile, requested_provider='ollama')
    forbidden.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize('primary_error', ['unavailable', 'authentication', 'timeout'])
async def test_daily_limit_from_a_fallback_retains_the_typed_failure(profile, primary_error):
    from app.services.ai_provider import GeminiAuthError, ProviderUnavailableError
    from app.services.resilient_provider import ResilientAIProvider
    from tests.test_provider_fallback import FailingProvider, job
    error = {'unavailable': ProviderUnavailableError('Unavailable'), 'authentication': GeminiAuthError('Authentication failed'),
             'timeout': TimeoutError()}[primary_error]
    provider = ResilientAIProvider({'ollama': FailingProvider('ollama', error),
                                    'gemini': FailingProvider('gemini', DailyAIBudgetExceeded())})
    with pytest.raises(DailyAIBudgetExceeded):
        await provider.tailor(job(), profile, requested_provider='ollama')


@pytest.mark.asyncio
async def test_normal_worker_retains_budget_429_instead_of_network_502(tmp_path, monkeypatch):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {}, 'synthetic-worker-quota')
    async def execute(task, state):
        manager._stop_event.set()
        raise DailyAIBudgetExceeded()
    monkeypatch.setattr(manager, '_execute_task', execute)
    await asyncio.wait_for(manager._worker_loop(SimpleNamespace()), timeout=3)
    result = manager.get_task(task.task_id)
    assert result.status == TaskStatus.FAILED
    assert result.error_status_code == 429
    assert result.stage == 'Daily AI call limit reached'
    assert 'UTC daily reset' in result.error
