import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import httpx
from starlette.testclient import TestClient

from app.main import app
from app.models.job import JobExtraction
from app.services.mock_provider import MockAIProvider
from app.services.task_manager import TaskKind, TaskManager, TaskStatus
from tests.test_queue_controls import login


def headers(client, key='synthetic-batch-1'):
    return {'X-CSRF-Token': client.cookies.get('csrf_token'), 'Idempotency-Key': key}


def test_batch_auth_upload_options_and_idempotency(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        assert client.get('/api/v1/batches/' + 'a' * 32).status_code == 401
        login(client)
        body = {'urls': ['https://example.com/job', 'https://example.com/job'], 'llm_provider': 'mock'}
        assert client.post('/api/v1/batches', json=body).status_code == 403
        created = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert created.status_code == 202, created.text
        repeated = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert repeated.json()['task_id'] == created.json()['task_id']
        conflict = client.post('/api/v1/batches', json={**body, 'template_name': 'modern_sidebar'}, headers=headers(client))
        assert conflict.status_code == 409
        task = app.state.task_manager.get_task(created.json()['task_id'])
        assert task.kind == TaskKind.BATCH and task.keep_history
        assert len(task.payload['batch']['urls']) == 1
        assert client.get(created.json()['status_url']).status_code == 200
        uploaded = client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', b'https://example.com/other')},
            data={'options': json.dumps({'llm_provider': 'mock', 'template_name': 'modern_sidebar', 'export': False})},
            headers=headers(client, 'synthetic-upload-1'))
        assert uploaded.status_code == 202, uploaded.text
        uploaded_task = app.state.task_manager.get_task(uploaded.json()['task_id'])
        assert uploaded_task.payload['batch']['template_name'] == 'modern_sidebar'
        assert uploaded_task.payload['batch']['export'] is False
        invalid = client.post('/api/v1/batches/upload', files={'file': ('jobs.txt', b'not a URL')},
                              headers=headers(client, 'invalid-upload-1'))
        assert invalid.status_code == 422
        assert client.get('/api/v1/batches/' + 'f' * 32).status_code == 404


def test_batch_worker_saves_normal_drafts_continues_errors_and_exports(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    exported = []

    async def export(state, draft_id, **options):
        state.storage.load_draft(draft_id)
        exported.append(options)
        if len(exported) == 1:
            raise ValueError('Confirm the displayed summary before export')
        return 'synthetic-export'

    async def extract(url):
        if url.endswith('/error'):
            raise RuntimeError('Synthetic extraction failure')
        if url.endswith('/blocked'):
            return JobExtraction(source=url, extraction_method='manual_required', failure_reason='blocked')
        return JobExtraction(source=url, extraction_method='html', company='Synthetic', role='Support Engineer',
                             job_description='Requirements\nPython automation and Linux support knowledge required.')

    monkeypatch.setattr('app.services.batch.export_draft', export)
    with TestClient(app) as client:
        login(client)
        app.state.job_extractor.extract = AsyncMock(side_effect=extract)
        response = client.post('/api/v1/batches', json={'urls': [f'https://example.com/{p}' for p in
            ['error', 'blocked', 'first', 'second']], 'llm_provider': 'mock', 'template_name': 'modern_sidebar'},
            headers=headers(client))
        manager = app.state.task_manager
        task = manager.get_task(response.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, app.state))
        done = manager.get_task(task.task_id)
        assert done.status == TaskStatus.COMPLETED
        items = done.result['items']
        assert [i['status'] for i in items] == ['failed', 'manual_required', 'review_required', 'completed']
        assert items[-1]['pdf_url'] == '/download/synthetic-export/pdf'
        for item in items[2:]:
            child = manager.get_task(item['task_id'])
            assert child.kind == TaskKind.TAILOR and child.keep_history
            assert child.status == TaskStatus.COMPLETED
            job, _ = app.state.storage.load_draft(item['draft_id'])
            assert str(job.job_url) == item['url']
        assert exported == [{'template_name': 'modern_sidebar', 'require_reliable_analysis': True}] * 2
        history = client.get('/history')
        assert history.status_code == 200
        assert items[-1]['draft_id'] in history.text


def test_batch_end_to_end_exports_downloads_and_idempotent_completion(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        app.state.job_extractor.extract = AsyncMock(return_value=JobExtraction(
            source='https://example.com/job', extraction_method='html', company='Synthetic', role='Support Engineer',
            offer_valid_until='2026-11-30',
            job_description='Requirements\nKnowledge of Python\nKnowledge of Linux'))
        body = {'urls': ['https://example.com/job'], 'llm_provider': 'mock'}
        created = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert created.status_code == 202
        manager = app.state.task_manager
        task = manager.get_task(created.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, app.state))
        result = client.get(created.json()['status_url']).json()
        item = result['result']['items'][0]
        assert item['status'] == 'completed', item
        assert item['offer_valid_until'] == '2026-11-30'
        assert app.state.storage.load_draft(item['draft_id'])[0].offer_valid_until.isoformat() == '2026-11-30'
        assert app.state.storage.load_application(item['slug'])[0].offer_valid_until.isoformat() == '2026-11-30'
        pdf = client.get(item['pdf_url'])
        assert pdf.status_code == 200 and pdf.content.startswith(b'%PDF')
        docx = client.get(item['docx_url'])
        assert docx.status_code == 200 and docx.content.startswith(b'PK')
        assert client.get(item['preview_url']).status_code == 200
        assert item['slug'] in client.get('/history').text
        repeated = client.post('/api/v1/batches', json=body, headers=headers(client))
        assert repeated.status_code == 200
        assert repeated.json()['task_id'] == task.task_id
        assert 'Retry-After' not in repeated.headers
        assert app.state.job_extractor.extract.await_count == 1


def test_batch_openapi_contract_and_discovery(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        app.state.provider.providers['ollama'].available_models = AsyncMock(return_value=['synthetic:1b'])
        options = client.get('/api/v1/batches/options')
        assert options.status_code == 200
        assert options.json()['ollama_models'] == ['synthetic:1b']
        assert options.json()['templates'] == ['ats_classic', 'modern_sidebar']
        schema = client.get('/openapi.json').json()
        endpoint = schema['paths']['/api/v1/batches']['post']
        assert endpoint['security'] == [{'SessionCookie': []}]
        assert {'200', '202', '401', '403', '409', '413', '422', '429'} <= set(endpoint['responses'])
        assert {p['name'] for p in endpoint['parameters']} == {'X-CSRF-Token', 'Idempotency-Key'}


def test_batch_uses_real_ssrf_guard_before_any_transport(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    calls = []

    def forbidden_transport(request):
        calls.append(request)
        raise AssertionError('Unsafe URLs must never reach HTTP transport')

    with TestClient(app) as client:
        login(client)
        app.state.job_extractor.fetcher.transport = httpx.MockTransport(forbidden_transport)
        response = client.post('/api/v1/batches', json={'urls': [
            'http://127.0.0.1/private', 'http://169.254.169.254/latest/meta-data/',
            'http://[::1]/private', 'http://localhost/private'], 'llm_provider': 'mock'}, headers=headers(client))
        assert response.status_code == 202
        manager = app.state.task_manager
        task = manager.get_task(response.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, app.state))
        items = client.get(response.json()['status_url']).json()['result']['items']
        assert all(item['status'] == 'manual_required' and item['error'] == 'unsafe_url' for item in items)
        assert calls == []


def test_idempotent_admission_serializes_workers_and_returns_existing_when_full(tmp_path):
    managers = [TaskManager(tmp_path, max_pending=1), TaskManager(tmp_path, max_pending=1)]
    payload = {'batch': {'urls': ['https://example.com/job']}}
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(m.get_or_create_idempotent, TaskKind.BATCH, payload, 'synthetic-key') for m in managers]
        tasks = [future.result() for future in futures]
    assert tasks[0].task_id == tasks[1].task_id
    assert len(list((tmp_path / 'tasks').glob('*.json'))) == 1
    assert tasks[0].keep_history
    assert managers[0].get_or_create_idempotent(TaskKind.BATCH, payload, 'synthetic-key').task_id == tasks[0].task_id


def test_gemini_model_selection_is_local_to_batch_task(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    seen = []

    class SyntheticGemini(MockAIProvider):
        name = 'gemini'
        model = 'synthetic-default'

        async def tailor(self, job, profile, **kwargs):
            seen.append(self.model)
            return await super().tailor(job, profile)

    with TestClient(app) as client:
        login(client)
        original = SyntheticGemini(app.state.skills_bank)
        app.state.provider.providers['gemini'] = original
        app.state.job_extractor.extract = AsyncMock(return_value=JobExtraction(
            source='https://example.com/job', extraction_method='html', company='Synthetic', role='Support Engineer',
            job_description='Requirements\nPython automation and Linux support knowledge required.'))
        response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job'],
            'llm_provider': 'gemini', 'gemini_model': 'synthetic-selected', 'export': False}, headers=headers(client))
        assert response.status_code == 202, response.text
        manager = app.state.task_manager
        task = manager.get_task(response.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, app.state))
        item = manager.get_task(task.task_id).result['items'][0]
        assert item['status'] == 'draft_ready', item
        assert item['model_used'] == 'synthetic-selected'
        assert seen == ['synthetic-selected']
        assert original.model == 'synthetic-default'


def test_batch_restart_recovery_preserves_finished_items_and_marks_unfinished(tmp_path):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.BATCH, {'batch': {'urls': ['https://example.com/job']}}, 'synthetic-recovery')
    task.status = TaskStatus.RUNNING
    task.result = {'items': [{'url': 'https://example.com/one', 'status': 'completed', 'draft_id': 'saved'},
                             {'url': 'https://example.com/two', 'status': 'running'},
                             {'url': 'https://example.com/three', 'status': 'queued'}]}
    manager._save_task(task)
    assert asyncio.run(manager.recover_on_startup()) == 1
    recovered = manager.get_task(task.task_id)
    assert recovered.status == TaskStatus.FAILED
    assert [item['status'] for item in recovered.result['items']] == ['completed', 'failed', 'failed']
    assert recovered.result['items'][0]['draft_id'] == 'saved'


def test_batch_per_offer_deadline_does_not_skip_later_offers(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)

    async def extract(url):
        if url.endswith('/slow'):
            await asyncio.Event().wait()
        return JobExtraction(source=url, extraction_method='html', company='Synthetic', role='Support Engineer',
                             job_description='Requirements\nPython automation and Linux support knowledge required.')

    with TestClient(app) as client:
        login(client)
        app.state.job_extractor.extract = AsyncMock(side_effect=extract)
        response = client.post('/api/v1/batches', json={'urls': ['https://example.com/slow', 'https://example.com/fast'],
            'llm_provider': 'mock', 'export': False}, headers=headers(client))
        manager = app.state.task_manager
        manager.budget_seconds = .5
        task = manager.get_task(response.json()['task_id'])
        task.status = TaskStatus.RUNNING
        task.started_at = task.created_at
        manager._save_task(task)
        asyncio.run(manager._execute_task(task, app.state))
        done = manager.get_task(task.task_id)
        assert done.status == TaskStatus.COMPLETED
        assert [item['status'] for item in done.result['items']] == ['failed', 'draft_ready']
