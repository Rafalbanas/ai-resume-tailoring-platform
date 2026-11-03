"""Exercise actual batch routing rather than a reimplementation of its policy."""
import asyncio
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.main import app
from app.models.batch import BatchRequest
from app.models.job import JobExtraction
from app.services.ai_provider import ProviderUnavailableError
from app.services.mock_provider import MockAIProvider
from app.services.task_manager import TaskManager, TaskStatus
from tests.test_queue_controls import login


@pytest.mark.parametrize('value', ['false', 'yes', 1, 0, None])
def test_fallback_consent_requires_a_json_boolean(value):
    with pytest.raises(ValidationError):
        BatchRequest(urls=['https://example.com/job'], allow_fallback=value)


def test_fallback_is_opt_in():
    assert BatchRequest(urls=['https://example.com/job']).allow_fallback is False
    assert BatchRequest(urls=['https://example.com/job'], allow_fallback=True).allow_fallback is True


@pytest.mark.parametrize('consent,global_enabled,expected_cloud_calls,legacy',
                         [(None, True, 0, False), (False, True, 0, False),
                          (True, True, 1, False), (True, False, 0, False), (None, True, 0, True)])
def test_batch_calls_cloud_only_with_consent_and_global_permission(monkeypatch, consent, global_enabled, expected_cloud_calls, legacy):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    cloud_calls = []

    class Local(MockAIProvider):
        name = 'ollama'
        model = 'synthetic-local'

        async def tailor(self, job, profile, **kwargs):
            raise ProviderUnavailableError('Synthetic local failure')

    class Cloud(MockAIProvider):
        name = 'gemini'
        model = 'synthetic-cloud'
        api_key = 'synthetic'

        async def tailor(self, job, profile, **kwargs):
            cloud_calls.append(True)
            return await super().tailor(job, profile)

    with TestClient(app) as client:
        login(client)
        state = app.state
        state.provider.providers['ollama'] = Local(state.skills_bank)
        state.provider.providers['ollama'].with_selection = lambda *args: state.provider.providers['ollama']
        state.provider.providers['gemini'] = Cloud(state.skills_bank)
        state.provider.fallback_enabled = global_enabled
        state.job_extractor.extract = AsyncMock(return_value=JobExtraction(source='https://example.com/job',
            extraction_method='html', company='Synthetic', role='Support Engineer',
            job_description='Requirements\nPython automation and Linux support knowledge required.'))
        body = {'urls': ['https://example.com/job'], 'llm_provider': 'ollama', 'export': False}
        if consent is not None:
            body['allow_fallback'] = consent
        response = client.post('/api/v1/batches', json=body, headers={
            'X-CSRF-Token': client.cookies.get('csrf_token'), 'Idempotency-Key': 'synthetic-consent-test'})
        assert response.status_code == 202, response.text
        manager = state.task_manager
        if legacy:
            original = manager._execute_tailor

            async def execute_legacy_child(child, state):
                child.payload.pop('allow_fallback')
                manager._save_task(child)
                await original(child, state)

            monkeypatch.setattr(manager, '_execute_tailor', execute_legacy_child)
        task = manager.get_task(response.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, state))
        item = manager.get_task(task.task_id).result['items'][0]
        assert len(cloud_calls) == expected_cloud_calls
        assert item['status'] == ('draft_ready' if expected_cloud_calls else 'failed')
        assert state.provider.fallback_enabled is global_enabled
        if not legacy:
            assert manager.get_task(item['task_id']).payload['allow_fallback'] is (consent is True)
