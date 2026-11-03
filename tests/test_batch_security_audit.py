import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.models.batch import BatchRequest
from app.models.job import JobRequest
from app.services.task_manager import TaskKind, TaskManager
from tests.test_queue_controls import login


def test_upgrade_retry_normalizes_optional_defaults_without_paid_rerun(tmp_path):
    manager = TaskManager(tmp_path)
    old = BatchRequest(urls=['https://example.com/job']).model_dump(mode='json')
    old.pop('allow_fallback')
    task = manager.create_task(TaskKind.BATCH, {'batch': old}, 'synthetic-upgrade')
    current = {'batch': BatchRequest(urls=['https://example.com/job']).model_dump(mode='json')}
    assert manager.get_or_create_idempotent(TaskKind.BATCH, current, 'synthetic-upgrade').task_id == task.task_id
    with pytest.raises(HTTPException) as error:
        manager.get_or_create_idempotent(TaskKind.BATCH,
            {'batch': {**current['batch'], 'allow_fallback': True}}, 'synthetic-upgrade')
    assert error.value.status_code == 409


def test_csrf_from_old_session_cannot_be_replayed_even_with_matching_cookie(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        old_csrf = client.cookies.get('csrf_token')
        login(client)
        assert client.cookies.get('csrf_token') != old_csrf
        for cookie in client.cookies.jar:
            if cookie.name == 'csrf_token':
                cookie.value = old_csrf
        response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job']},
            headers={'X-CSRF-Token': old_csrf, 'Idempotency-Key': 'synthetic-old-session'})
        assert response.status_code == 403
        assert not list(app.state.task_manager.tasks_dir.glob('*.json'))


def test_ui_retry_of_legacy_batch_child_preserves_local_only_default(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        manager = app.state.task_manager
        job = JobRequest(company='Synthetic', role='Engineer', job_description='Python automation support requirements.')
        task = manager.create_task(TaskKind.TAILOR, {'job': job.model_dump(mode='json'), 'llm_provider': 'ollama'},
                                   'batch:legacy-parent:0')
        from app.services.task_manager import TaskStatus
        task.status = TaskStatus.FAILED
        manager._save_task(task)
        result = client.post(f'/tasks/{task.task_id}/retry', data={'csrf_token': client.cookies.get('csrf_token')},
                             headers={'Accept': 'application/json'})
        assert result.status_code == 202, result.text
        retry = manager.get_task(result.json()['task_id'])
        assert retry.payload['allow_fallback'] is False
        assert 'allow_fallback' not in manager.get_task(task.task_id).payload
