"""Cooperative cancellation: no active writer is killed and no saved result deleted."""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.models.job import JobExtraction
from app.services.batch import run_batch
from app.services.task_manager import TaskKind, TaskManager, TaskStatus
from tests.test_batch_api import headers
from tests.test_queue_controls import login


def batch(manager, *, running=False, export=False):
    task = manager.create_task(TaskKind.BATCH, {'batch': {
        'urls': ['https://example.com/first', 'https://example.com/second'],
        'llm_provider': 'mock', 'export': export}}, 'synthetic-batch')
    if running:
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.now(timezone.utc).isoformat()
        manager._save_task(task)
    return task


def state(extract):
    return SimpleNamespace(job_extractor=SimpleNamespace(extract=extract),
                           resource_budget=SimpleNamespace(check_disk=lambda: None, mutation_slots=asyncio.Semaphore(1)))


async def extracted(url):
    return JobExtraction(source=url, extraction_method='html', company='Synthetic', role='Engineer',
                         job_description='Requirements\nKnowledge of Linux and Python support.')


def test_cancel_queued_batch_is_durable_idempotent_and_frees_capacity(tmp_path):
    manager = TaskManager(tmp_path, max_pending=1)
    task = batch(manager)
    result = manager.request_batch_cancel(task.task_id)
    assert result.status == TaskStatus.CANCELLED
    assert result.cancellation_requested and result.keep_history
    assert all(i['status'] == 'cancelled' for i in result.result['items'])
    assert manager._queue.empty()
    assert manager.request_batch_cancel(task.task_id).model_dump() == result.model_dump()
    assert TaskManager(tmp_path).get_task(task.task_id).status == TaskStatus.CANCELLED
    manager.create_task(TaskKind.TAILOR, {}, 'next')


def test_running_marker_survives_stale_progress_saves_and_stays_account_local(tmp_path):
    manager = TaskManager(tmp_path / 'owner')
    task = batch(manager, running=True)
    manager.request_batch_cancel(task.task_id)
    manager._save_task(task.model_copy(update={'stage': 'A late progress write'}))
    assert manager.get_task(task.task_id).cancellation_requested
    assert TaskManager(tmp_path / 'owner').batch_cancel_requested(task.task_id)
    other = TaskManager(tmp_path / 'demo')
    with pytest.raises(HTTPException) as exc:
        other.request_batch_cancel(task.task_id)
    assert exc.value.status_code == 404
    assert not other.batch_cancel_requested(task.task_id)
    with pytest.raises(HTTPException):
        manager.request_batch_cancel('../outside')


def test_non_batch_and_finished_tasks_are_not_mutated(tmp_path):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {}, 'individual')
    with pytest.raises(HTTPException) as exc:
        manager.request_batch_cancel(task.task_id)
    assert exc.value.status_code == 409
    done = batch(manager)
    done.status = TaskStatus.COMPLETED
    done.result = {'items': [], 'history_url': '/history', 'redirect_url': '/history'}
    manager._save_task(done)
    before = manager._task_path(done.task_id).read_bytes()
    assert manager.request_batch_cancel(done.task_id).status == TaskStatus.COMPLETED
    assert before == manager._task_path(done.task_id).read_bytes()
    assert not manager.batch_cancel_requested(done.task_id)


@pytest.mark.asyncio
@pytest.mark.parametrize('during_export', [False, True])
async def test_active_offer_finishes_before_parent_cancels_and_next_offer_never_starts(tmp_path, monkeypatch, during_export):
    manager = TaskManager(tmp_path)
    task = batch(manager, running=True, export=during_export)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []
    saved = tmp_path / 'saved-analysis'

    async def extract(url):
        calls.append(url)
        return await extracted(url)

    async def execute(child, app_state):
        if not during_export:
            entered.set()
            await finish.wait()
        saved.write_text('complete verified result')
        child.status = TaskStatus.COMPLETED
        child.result = {'draft_id': 'a' * 32}
        manager._save_task(child)

    async def export(*args, **kwargs):
        entered.set()
        await finish.wait()
        (tmp_path / 'saved.pdf').write_bytes(b'%PDF-synthetic')
        return 'synthetic-saved'

    monkeypatch.setattr(manager, '_execute_task', execute)
    monkeypatch.setattr('app.services.batch.export_draft', export)
    executing = asyncio.create_task(run_batch(manager, task, state(extract)))
    await asyncio.wait_for(entered.wait(), 2)
    requested = manager.request_batch_cancel(task.task_id)
    assert requested.status == TaskStatus.RUNNING and requested.cancellation_requested
    assert not executing.done()
    finish.set()
    await asyncio.wait_for(executing, 2)
    done = manager.get_task(task.task_id)
    assert done.status == TaskStatus.CANCELLED
    assert calls == ['https://example.com/first']
    assert [i['status'] for i in done.result['items']] == ['completed' if during_export else 'draft_ready', 'cancelled']
    assert manager.get_task(done.result['items'][0]['task_id']).status == TaskStatus.COMPLETED
    assert saved.read_text() == 'complete verified result'
    if during_export:
        assert (tmp_path / 'saved.pdf').read_bytes() == b'%PDF-synthetic'


@pytest.mark.asyncio
async def test_cancel_during_extraction_does_not_start_a_model_call(tmp_path):
    manager = TaskManager(tmp_path)
    task = batch(manager, running=True)
    async def extract(url):
        manager.request_batch_cancel(task.task_id)
        return await extracted(url)
    await run_batch(manager, task, state(extract))
    done = manager.get_task(task.task_id)
    assert done.status == TaskStatus.CANCELLED
    assert all(i['status'] == 'cancelled' for i in done.result['items'])
    assert len(list(manager.tasks_dir.glob('*.json'))) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['error', 'deadline'])
async def test_cancelled_offer_failure_is_preserved_and_worker_runs_next_task(tmp_path, monkeypatch, failure):
    manager = TaskManager(tmp_path, budget_seconds=.05 if failure == 'deadline' else 5)
    parent = batch(manager)
    independent = manager.create_task(TaskKind.TAILOR, {}, 'independent')
    entered, finish = asyncio.Event(), asyncio.Event()
    original_execute = manager._execute_task
    calls = []

    async def execute(task, app_state):
        if task.kind == TaskKind.BATCH:
            return await original_execute(task, app_state)
        calls.append(task.task_id)
        if task.task_id != independent.task_id:
            entered.set()
            await finish.wait()
            raise RuntimeError('Synthetic provider failure')
        task.status = TaskStatus.COMPLETED
        task.result = {'synthetic': True}
        manager._save_task(task)

    monkeypatch.setattr(manager, '_execute_task', execute)
    manager.start_worker(state(extracted))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        manager.request_batch_cancel(parent.task_id)
        if failure == 'error':
            finish.set()
        await asyncio.wait_for(manager._queue.join(), 3)
        done = manager.get_task(parent.task_id)
        assert done.status == TaskStatus.CANCELLED
        assert [item['status'] for item in done.result['items']] == ['failed', 'cancelled']
        assert ('deadline exceeded' if failure == 'deadline' else 'processing failed') in done.result['items'][0]['error']
        assert manager.get_task(independent.task_id).status == TaskStatus.COMPLETED
        assert len(calls) == 2
    finally:
        manager.stop_worker()
        await manager._worker_task


@pytest.mark.asyncio
async def test_restart_preserves_cancellation_marker_and_saved_results(tmp_path):
    manager = TaskManager(tmp_path)
    task = batch(manager, running=True)
    task.result = {'items': [{'url': 'https://example.com/first', 'status': 'draft_ready', 'draft_id': 'd' * 32}]}
    manager._save_task(task)
    manager.request_batch_cancel(task.task_id)
    restarted = TaskManager(tmp_path)
    await restarted.recover_on_startup()
    recovered = restarted.get_task(task.task_id)
    assert recovered.cancellation_requested
    assert recovered.status == TaskStatus.FAILED  # Existing recovery never restarts paid work.
    assert recovered.result == task.result


def test_cancel_routes_enforce_auth_csrf_kind_and_render_saved_results(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        path = '/api/v1/batches/' + 'a' * 32 + '/cancel'
        assert client.post(path, headers={'X-CSRF-Token': 'invalid'}).status_code == 401
        login(client)
        manager = app.state.task_manager
        task = batch(manager)
        path = f'/api/v1/batches/{task.task_id}/cancel'
        assert client.post(path, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
        cancelled = client.post(path, headers=headers(client))
        assert cancelled.status_code == 200
        assert cancelled.json()['status'] == 'cancelled' and cancelled.json()['cancellation_requested']
        view = client.get(f'/tasks/{task.task_id}/view')
        assert view.status_code == 200
        assert 'Batch cancelled — saved results kept' in view.text
        assert client.post(path, headers=headers(client)).json()['status'] == 'cancelled'
        other = manager.create_task(TaskKind.TAILOR, {}, 'other')
        assert client.post(f'/api/v1/batches/{other.task_id}/cancel', headers=headers(client)).status_code == 409
        queued = manager.create_task(TaskKind.BATCH, task.payload, 'form-test')
        form = f'/queue/tasks/{queued.task_id}/cancel-batch'
        assert client.post(form, data={'csrf_token': 'invalid'}).status_code == 403
        assert client.post(form, data={'csrf_token': client.cookies.get('csrf_token')}, follow_redirects=False).status_code == 303


@pytest.mark.parametrize('root', ['', '/workspace'])
def test_actual_endpoints_under_deployment_lock_keep_security(tmp_path, monkeypatch, root):
    from deploy.k8s.production.runtime import DeploymentAdmission
    from tests.test_deployment_cancel_admission import locked

    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(DeploymentAdmission(app, tmp_path), root_path=root) as client:
        login(client)
        task = batch(app.state.task_manager, running=True)
        api = f'{root}/api/v1/batches/{task.task_id}/cancel'
        form = f'{root}/queue/tasks/{task.task_id}/cancel-batch'
        with locked(tmp_path):
            assert client.post(root + '/queue/pause', data={'csrf_token': client.cookies.get('csrf_token')}).status_code == 503
            assert client.post(api, headers={'X-CSRF-Token': 'invalid'}).status_code == 403
            assert client.post(form, data={'csrf_token': 'invalid'}).status_code == 403
            response = client.post(api, headers=headers(client))
            assert response.status_code == 202
            assert response.json()['status'] == 'running'
            assert response.json()['cancellation_requested']
            assert client.post(form, data={'csrf_token': client.cookies.get('csrf_token')},
                               follow_redirects=False).status_code == 303
            monkeypatch.setattr(app.state.settings, 'demo_mode', True)
            assert client.post(api, headers=headers(client)).status_code == 403
            assert client.post(form, data={'csrf_token': client.cookies.get('csrf_token')}).status_code == 403
            client.cookies.clear()
            assert client.post(api, headers={'X-CSRF-Token': 'invalid'}).status_code == 401
            assert client.post(form, data={'csrf_token': 'invalid'}).status_code == 401
