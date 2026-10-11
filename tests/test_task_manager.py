from datetime import datetime, timezone

import pytest
from starlette.testclient import TestClient

import app.routes.web as web_routes
from app.main import app
from app.services.task_manager import TaskKind, TaskManager, TaskRecord, TaskStatus, compute_idempotency_key


@pytest.fixture
def temp_task_manager(tmp_path):
    tm = TaskManager(tmp_path, budget_seconds=5.0)
    return tm


@pytest.mark.asyncio
async def test_startup_recovery_cleans_orphaned_tasks(tmp_path):
    tm = TaskManager(tmp_path, budget_seconds=10.0)
    # Create two orphaned tasks (one queued, one running) and one completed
    t1 = TaskRecord(
        task_id="11111111111111111111111111111111",
        kind=TaskKind.TAILOR,
        idempotency_key="key1",
        status=TaskStatus.QUEUED,
        created_at=datetime.now(timezone.utc).isoformat(),
    )
    t2 = TaskRecord(
        task_id="22222222222222222222222222222222",
        kind=TaskKind.TAILOR,
        idempotency_key="key2",
        status=TaskStatus.RUNNING,
        created_at=datetime.now(timezone.utc).isoformat(),
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    t3 = TaskRecord(
        task_id="33333333333333333333333333333333",
        kind=TaskKind.TAILOR,
        idempotency_key="key3",
        status=TaskStatus.COMPLETED,
        created_at=datetime.now(timezone.utc).isoformat(),
        completed_at=datetime.now(timezone.utc).isoformat(),
    )
    tm._save_task(t1)
    tm._save_task(t2)
    tm._save_task(t3)

    # Perform startup recovery
    recovered_count = await tm.recover_on_startup()
    assert recovered_count == 2

    # Check that t1 and t2 are now failed with explanatory error
    t1_after = tm.get_task("11111111111111111111111111111111")
    assert t1_after.status == TaskStatus.FAILED
    assert "restart" in t1_after.error
    assert t1_after.completed_at is not None

    t2_after = tm.get_task("22222222222222222222222222222222")
    assert t2_after.status == TaskStatus.FAILED
    assert "restart" in t2_after.error

    # Check that completed task was NOT modified
    t3_after = tm.get_task("33333333333333333333333333333333")
    assert t3_after.status == TaskStatus.COMPLETED


@pytest.mark.asyncio
async def test_idempotency_prevents_duplicate_active_tasks(temp_task_manager):
    key = compute_idempotency_key("tailor", company="Acme", role="Engineer")
    task1 = temp_task_manager.create_task(TaskKind.TAILOR, payload={"test": 1}, idempotency_key=key)

    # Looking for active task with the same key returns task1
    active = temp_task_manager.find_active_by_idempotency_key(key)
    assert active is not None
    assert active.task_id == task1.task_id


def test_task_status_and_view_endpoints(monkeypatch):
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        client.auth = ("audit-tests", "isolated-test-password")
        # 1. 404 for unknown task
        res_404 = client.get("/tasks/non_existent_task_id")
        assert res_404.status_code == 404

        # 2. Submit /analyze and verify 202
        post_res = client.post(
            "/analyze",
            data={
                "company": "Task Corp",
                "role": "Cloud Architect",
                "job_description": "We need a cloud engineer with Python and Docker experience in production.",
                "csrf_token": "token",
            },
            headers={"Accept": "application/json"},
        )
        assert post_res.status_code == 202
        data = post_res.json()
        assert "task_id" in data
        assert data["status"] in ("queued", "running", "completed")
        task_id = data["task_id"]

        # 3. GET /tasks/{task_id} returns 200 with task status
        status_res = client.get(f"/tasks/{task_id}")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["task_id"] == task_id
        assert status_data["kind"] == "tailor"
        assert "stage" in status_data
        assert "progress_percent" in status_data

        # 4. GET /tasks/{task_id}/view renders HTML progress page or redirects if completed
        view_res = client.get(f"/tasks/{task_id}/view", follow_redirects=False)
        assert view_res.status_code in (200, 303)
        if view_res.status_code == 200:
            assert "ZADANIE W TLE" in view_res.text or "Cloud Architect" in view_res.text


def test_task_endpoints_require_authorization(monkeypatch):
    # Ensure unauthenticated request is blocked by guard
    with TestClient(app) as client:
        res = client.get("/tasks/some_id")
        assert res.status_code in (401, 403)

        res_view = client.get("/tasks/some_id/view")
        assert res_view.status_code in (401, 403)
