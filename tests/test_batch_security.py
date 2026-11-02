"""Account, CSRF and resource-admission regression coverage; no external calls."""
import json

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.services.task_manager import TaskKind, TaskManager
from tests.test_queue_controls import login
from tests.test_shared_login import shared_app, sign_in  # noqa: F401


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        yield client


def headers(client, **extra):
    return {'X-CSRF-Token': client.cookies.get('csrf_token'), 'Idempotency-Key': 'synthetic-security', **extra}


def test_batch_security_no_auth_post_json(client):
    assert client.post('/api/v1/batches', json={'urls': ['https://example.com']}).status_code == 401
    assert client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', b'https://example.com')}).status_code == 401


def test_batch_security_csrf_protection(client):
    login(client)
    body = {'urls': ['https://example.com'], 'llm_provider': 'mock'}
    assert client.post('/api/v1/batches', json=body).status_code == 403
    assert client.post('/api/v1/batches', json=body,
                       headers=headers(client, **{'X-CSRF-Token': 'invalid'})).status_code == 403
    assert client.post('/api/v1/batches', json=body,
                       headers=headers(client, Origin='https://foreign.example')).status_code == 403
    assert not list(app.state.task_manager.tasks_dir.glob('*.json'))


@pytest.mark.parametrize('urls', [[f'https://example.com/{i}' for i in range(21)], ['https://example.com'] * 21])
def test_batch_security_too_many_urls(client, urls):
    login(client)
    assert client.post('/api/v1/batches', json={'urls': urls}, headers=headers(client)).status_code == 422


@pytest.mark.parametrize('content', [b'a' * 65537, b'\xff\xfe\xfd', b'  \n\t', b''])
def test_batch_security_invalid_files(client, content):
    login(client)
    assert client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', content)},
                       headers=headers(client)).status_code == 422
    assert not list(app.state.task_manager.tasks_dir.glob('*.json'))


@pytest.mark.parametrize('options', ['not-json', '[]', 'null', '1',
    json.dumps({'urls': ['https://other.example']}), json.dumps({'extra': 'value'})])
def test_batch_security_options_injection(client, options):
    login(client)
    assert client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', b'https://example.com')},
                       data={'options': options}, headers=headers(client)).status_code == 422


def test_batch_security_unknown_llm_provider(client):
    login(client)
    assert client.post('/api/v1/batches', json={'urls': ['https://example.com'], 'llm_provider': 'unknown'},
                       headers=headers(client)).status_code == 422


def test_batch_security_demo_access(client, monkeypatch):
    login(client)
    monkeypatch.setattr(app.state.settings, 'demo_mode', True)
    assert client.post('/api/v1/batches', json={'urls': ['https://example.com']},
                       headers=headers(client)).status_code == 403
    assert not list(app.state.task_manager.tasks_dir.glob('*.json'))


def test_batch_security_wrong_type_status(client):
    login(client)
    task = app.state.task_manager.create_task(TaskKind.TAILOR, {}, 'synthetic-other-kind')
    assert client.get(f'/api/v1/batches/{task.task_id}').status_code == 404
    assert client.get('/api/v1/batches/not-a-valid-task-id').status_code == 404


def test_batch_security_queue_and_request_body_limits(client):
    login(client)
    app.state.task_manager.max_pending = 1
    body = {'urls': ['https://example.com'], 'llm_provider': 'mock'}
    assert client.post('/api/v1/batches', json=body, headers=headers(client)).status_code == 202
    assert client.post('/api/v1/batches', json=body,
                       headers=headers(client, **{'Idempotency-Key': 'another-security-key'})).status_code == 429
    assert client.post('/api/v1/batches/upload', content=b'a' * (512 * 1024 + 1),
                       headers=headers(client)).status_code == 413


def test_batch_security_real_account_isolation(shared_app, monkeypatch):  # noqa: F811 - imported pytest fixture
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(shared_app) as client:
        assert sign_in(client, 'owner').status_code == 303
        response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job'], 'llm_provider': 'mock'},
                               headers=headers(client))
        assert response.status_code == 202
        url = response.json()['status_url']
        assert sign_in(client, 'demo').status_code == 303
        assert client.get(url, headers={'X-Account': 'owner'}).status_code == 404
        assert client.get(url + '?account=owner').status_code == 404
        assert client.post('/api/v1/batches', json={'urls': ['https://example.com/job']},
                           headers=headers(client)).status_code == 403


def test_batch_root_path_urls(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app, root_path='/tailor') as client:
        login(client)
        response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job']}, headers=headers(client))
        assert response.status_code == 202, response.text
        assert response.json()['status_url'].startswith('/tailor/api/v1/batches/')
        assert response.headers['Location'] == response.json()['status_url']
        assert client.get(response.json()['status_url']).status_code == 200
