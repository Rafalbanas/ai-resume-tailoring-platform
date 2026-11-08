"""Deployment timing is informational; the live file lock is authoritative."""
import fcntl
import importlib.util
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app.services.deployment_status import deployment_status


def test_embedded_runtime_matches_reviewed_source():
    root = Path(__file__).resolve().parents[1] / 'deploy/k8s/production'
    resources = json.loads((root / 'resources.json').read_text())
    config = next(item for item in resources['items'] if item.get('metadata', {}).get('name') == 'cvtailor-runtime-code')
    assert config['data']['runtime.py'] == (root / 'runtime.py').read_text()


def test_deployment_read_endpoint_requires_session_and_does_not_cache(monkeypatch):
    from starlette.testclient import TestClient

    from app.main import app
    from app.services.task_manager import TaskManager
    from tests.test_deployment_cancel_admission import locked
    from tests.test_queue_controls import login

    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        denied = client.get('/deployment/status', follow_redirects=False)
        assert denied.status_code == 303 and denied.headers['location'].endswith('/login')
        login(client)
        assert client.get('/deployment/status').json() == {'in_progress': False}
        with locked(app.state.deployment_data_dir):
            response = client.get('/deployment/status')
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert response.json()['in_progress'] is True


def test_missing_lock_and_stale_metadata_do_not_claim_an_active_deployment(tmp_path):
    (tmp_path / '.deployment-status.json').write_text('{"phase":"rollout"}')
    assert deployment_status(tmp_path) == {'in_progress': False}
    (tmp_path / '.deployment-admission.lock').touch()
    assert deployment_status(tmp_path) == {'in_progress': False}


def test_locked_deployment_reports_only_safe_timing_and_bounds_expired_deadline(tmp_path):
    path = tmp_path / '.deployment-admission.lock'
    path.touch()
    fd = os.open(path, os.O_RDWR)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        now = datetime.now(timezone.utc)
        (tmp_path / '.deployment-status.json').write_text(json.dumps({
            'started_at': (now - timedelta(seconds=905)).isoformat(),
            'drain_deadline_at': (now - timedelta(seconds=5)).isoformat(),
            'phase': 'waiting_for_tasks', 'secret': 'must-not-leak'}))
        value = deployment_status(tmp_path)
        assert value['in_progress'] is True
        assert value['phase'] == 'waiting_for_tasks'
        assert value['drain_seconds_remaining'] == 0
        assert 'must-not-leak' not in str(value)
        (tmp_path / '.deployment-status.json').write_text('invalid JSON')
        assert deployment_status(tmp_path)['in_progress'] is True
        assert deployment_status(tmp_path)['drain_seconds_remaining'] is None
    finally:
        os.close(fd)
    assert deployment_status(tmp_path) == {'in_progress': False}


def test_status_permission_error_is_unknown_not_a_false_idle_signal(tmp_path, monkeypatch):
    def denied(*args):
        raise PermissionError('Synthetic permission denial')
    monkeypatch.setattr('app.services.deployment_status.os.open', denied)
    assert deployment_status(tmp_path) == {'in_progress': None}


def test_real_deployer_drain_publishes_safe_metadata_and_timeout_releases_lock(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'deploy/k8s/production/deploy.py'
    spec = importlib.util.spec_from_file_location('status_deployer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA = tmp_path / 'main'
    (module.DATA / 'tasks').mkdir(parents=True)
    monkeypatch.setattr(module.os, 'fchown', lambda *args: None)
    descriptor = module.drain(timeout=10)
    try:
        value = deployment_status(module.DATA)
        assert value['in_progress'] is True and value['phase'] == 'rollout'
    finally:
        os.close(descriptor)
    (module.DATA / 'tasks/active.json').write_text('{"status":"running"}')
    import pytest
    with pytest.raises(TimeoutError, match='Active analyses'):
        module.drain(timeout=0)
    assert not (module.DATA / '.deployment-status.json').exists()
    assert deployment_status(module.DATA) == {'in_progress': False}
    descriptor = os.open(module.DATA / '.deployment-admission.lock', os.O_RDWR)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
        with pytest.raises(TimeoutError, match='Inflight requests'):
            module.drain(timeout=0)
        assert not (module.DATA / '.deployment-status.json').exists()
    finally:
        os.close(descriptor)
