import asyncio
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


def enqueue(manager, company):
    return manager.create_task(TaskKind.TAILOR, {'job': {'company': company, 'role': 'Engineer'}, 'private': 'not public'}, company)


def test_queue_snapshot_is_fifo_account_local_and_does_not_scan_history(tmp_path, monkeypatch):
    manager = TaskManager(tmp_path / 'owner')
    other = TaskManager(tmp_path / 'demo')
    running, first, second = [enqueue(manager, name) for name in ['Active', 'First', 'Second']]
    running.status = TaskStatus.RUNNING
    running.stage = 'Analyzing requirements'
    manager._save_task(running)
    manager._active_task_id = running.task_id
    manager._pending_task_ids.pop(running.task_id)
    enqueue(other, 'Private other account')
    monkeypatch.setattr(type(manager.tasks_dir), 'glob', lambda *args: pytest.fail('Activity must not scan history'))
    activity = manager.activity_for(second)
    assert activity['queue_position'] == 2
    assert activity['queued_ahead'] == 1
    assert [r['company'] for r in activity['queued_tasks']] == ['First', 'Second']
    assert activity['running_tasks'][0]['company'] == 'Active'
    assert 'private' not in str(activity)
    assert other.get_task(first.task_id) is None


def test_reject_keeps_history_frees_queue_slot_and_protects_running_tasks(tmp_path):
    manager = TaskManager(tmp_path, max_pending=2)
    first, second = enqueue(manager, 'First'), enqueue(manager, 'Second')
    rejected = manager.reject_queued(first.task_id)
    assert rejected.status == TaskStatus.REJECTED and rejected.keep_history
    assert manager.get_task(first.task_id).payload == first.payload
    third = enqueue(manager, 'Third')
    assert manager.activity_for(third)['queue_position'] == 2
    assert manager._queue.get_nowait() == second.task_id
    assert manager._queue.get_nowait() == third.task_id
    second.status = TaskStatus.RUNNING
    manager._save_task(second)
    with pytest.raises(HTTPException) as error:
        manager.reject_queued(second.task_id)
    assert error.value.status_code == 409


def test_pause_is_durable_and_invalid_state_fails_closed(tmp_path):
    manager = TaskManager(tmp_path)
    manager.set_paused(True)
    assert TaskManager(tmp_path).activity_for()['paused']
    manager.set_paused(False)
    assert not TaskManager(tmp_path).activity_for()['paused']
    (tmp_path / '.queue-control.json').write_text('{"paused":"false"}')
    assert TaskManager(tmp_path).activity_for()['paused']


@pytest.mark.asyncio
async def test_pause_allows_active_job_to_finish_but_holds_the_next(tmp_path, monkeypatch):
    manager = TaskManager(tmp_path)
    started, finish, next_started = asyncio.Event(), asyncio.Event(), asyncio.Event()
    first = enqueue(manager, 'First')
    second = enqueue(manager, 'Second')

    async def execute(task, state):
        if task.task_id == first.task_id:
            started.set()
            await finish.wait()
        else:
            next_started.set()
        current = manager.get_task(task.task_id)
        current.status = TaskStatus.COMPLETED
        manager._save_task(current)

    monkeypatch.setattr(manager, '_execute_task', execute)
    manager.start_worker(SimpleNamespace())
    try:
        await asyncio.wait_for(started.wait(), 1)
        manager.set_paused(True)
        finish.set()
        await asyncio.sleep(.05)
        assert manager.get_task(first.task_id).status == TaskStatus.COMPLETED
        assert manager.get_task(second.task_id).status == TaskStatus.QUEUED
        assert not next_started.is_set()
        manager.set_paused(False)
        await asyncio.wait_for(manager._queue.join(), 2)
        assert next_started.is_set()
    finally:
        manager.stop_worker()
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_reject_and_compact_do_not_finish_join_early(tmp_path):
    manager = TaskManager(tmp_path)
    first, second = enqueue(manager, 'First'), enqueue(manager, 'Second')
    joining = asyncio.create_task(manager._queue.join())
    await asyncio.sleep(0)
    manager.reject_queued(first.task_id)
    await asyncio.sleep(0)
    assert not joining.done()
    assert manager._queue.get_nowait() == second.task_id
    manager._queue.task_done()
    await asyncio.wait_for(joining, 1)


def test_deleting_requires_inactive_task_without_results(tmp_path):
    manager = TaskManager(tmp_path)
    task = enqueue(manager, 'Preserve')
    with pytest.raises(HTTPException):
        manager.delete_inactive_entry(task.task_id)
    manager.reject_queued(task.task_id)
    manager.delete_inactive_entry(task.task_id)
    assert manager.get_task(task.task_id) is None


def test_rejected_task_remains_in_analysis_history(tmp_path):
    from app.services.storage import Storage
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': {'company': 'Preserved', 'role': 'Engineer',
                               'job_description': 'Requirements\nKnowledge of Python and Linux administration.'}}, 'retained')
    manager.reject_queued(task.task_id)
    rows = Storage(tmp_path).analysis_history()
    assert any(row['status'] == 'rejected' and row['company'] == 'Preserved' for row in rows)


def login(client):
    client.get('/login')
    response = client.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password', 'csrf_token': client.cookies.get('csrf_token')})
    assert response.status_code == 200


def test_controls_require_auth_csrf_and_retain_retry_history(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        assert client.get('/queue/status', follow_redirects=False).status_code == 401
        login(client)
        manager = app.state.task_manager
        task = enqueue(manager, 'Queued')
        assert client.post('/queue/pause', data={'csrf_token': 'invalid'}).status_code == 403
        token = client.cookies.get('csrf_token')
        assert client.post('/queue/pause', data={'csrf_token': token}, follow_redirects=False).status_code == 303
        activity = client.get('/queue/status')
        assert activity.headers['cache-control'] == 'no-store'
        assert activity.json()['activity']['paused'] is True
        status = client.get(f'/tasks/{task.task_id}').json()
        assert status['activity']['queue_position'] == 1
        assert client.post(f'/queue/tasks/{task.task_id}/reject', data={'csrf_token': token}, follow_redirects=False).status_code == 303
        assert manager.get_task(task.task_id).status == TaskStatus.REJECTED
        retry = client.post(f'/queue/tasks/{task.task_id}/retry', data={'csrf_token': token}, follow_redirects=False)
        assert retry.status_code == 303
        assert task.task_id not in retry.headers['location']
        assert manager.get_task(task.task_id).keep_history


def test_polling_never_reissues_session_or_csrf_cookies(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        task = enqueue(app.state.task_manager, 'Cookie-safe poll')
        for path in ['/queue/status', f'/tasks/{task.task_id}']:
            response = client.get(path)
            assert response.status_code == 200
            assert not response.headers.get_list('set-cookie')
        assert client.get('/profile').headers.get_list('set-cookie')
