"""Adversarial regression cases for bounded parsing, resource admission and persistence."""
import asyncio
import io
import json
import subprocess
import sys
import threading
import time
from pathlib import Path

import httpx
import pytest
from fastapi import HTTPException
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.core.auth_boundary import validate_auth_settings
from app.main import create_app
from app.services.ai_provider import AIProviderError, ProviderResponseError
from app.services.bounded_http import bounded_post
from app.services.processing import ProcessingError, local_process
from app.services.reference_cvs import ReferenceCVLibrary
from app.services.resource_budget import ResourceBudget
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


@pytest.mark.parametrize('path,setting', [('/login', 'AUTH_BODY_SECONDS'),
    ('/settings/fallback', 'FORM_BODY_SECONDS'), ('/profile/photo', 'UPLOAD_BODY_SECONDS'),
    ('/generate/' + 'a' * 32, 'FORM_BODY_SECONDS')])
async def test_body_deadline_stops_slow_drip_and_releases_admission(path, setting, monkeypatch):
    import app.main as main
    from app.core import body_deadline
    app = create_app(main.get_settings())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        await login(client)
        monkeypatch.setattr(body_deadline, setting, 0.1)
        consumed = 0
        async def chunks():
            nonlocal consumed
            for _ in range(100):
                await asyncio.sleep(0.01)
                consumed += 1
                yield b'x'
        response = await asyncio.wait_for(client.post(path, content=chunks(), headers={
            'Content-Type': 'application/x-www-form-urlencoded',
            'X-CSRF-Token': client.cookies.get('csrf_token')}), 2)
        assert response.status_code == 408
        assert consumed < 100
        assert app.state.resource_budget.body_slots._value == 2
        assert app.state.resource_budget.mutation_slots._value == 1
        assert app.state.resource_budget.generation_slots._value == 4
        assert (await client.get('/profile')).status_code == 200
        await login(client)


@pytest.mark.parametrize('method', ['GET', 'POST'])
async def test_ai_response_deadline_is_total_not_reset_by_each_chunk(method):
    from app.services.bounded_http import bounded_get
    class Drip(httpx.AsyncByteStream):
        closed = False
        async def __aiter__(self):
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b' '
        async def aclose(self):
            self.closed = True
    stream = Drip()
    transport = httpx.MockTransport(lambda request: httpx.Response(200, stream=stream))
    async with httpx.AsyncClient(transport=transport, timeout=0.1) as client:
        with pytest.raises(httpx.ReadTimeout, match='total deadline'):
            operation = bounded_get if method == 'GET' else bounded_post
            await asyncio.wait_for(operation(client, 'https://model.example.test'), 2)
    assert stream.closed


async def test_finished_request_body_does_not_limit_response_duration():
    from app.core.body_deadline import deadline_receive
    messages = iter([{'type': 'http.request', 'body': b''}, {'type': 'http.disconnect'}])
    async def receive():
        return next(messages)
    bounded = deadline_receive(receive, 0.01)
    assert (await bounded())['type'] == 'http.request'
    await asyncio.sleep(0.02)
    assert (await bounded())['type'] == 'http.disconnect'


async def test_processing_body_deadline_releases_worker_slot(monkeypatch):
    import app.processing_server as server
    from app.core import body_deadline
    monkeypatch.setenv('PROCESSING_TOKEN', 'x' * 48)
    monkeypatch.setattr(body_deadline, 'UPLOAD_BODY_SECONDS', 0.1)
    monkeypatch.setattr(server, 'slots', asyncio.Semaphore(1))
    monkeypatch.setattr(server, 'local_process', lambda *args, **kwargs: {'ok': True, 'result': {}})
    async def chunks():
        for _ in range(100):
            await asyncio.sleep(0.01)
            yield b' '
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://worker') as client:
        headers = {'Authorization': 'Bearer ' + 'x' * 48}
        response = await asyncio.wait_for(client.post('/process', headers=headers, content=chunks()), 2)
        assert response.status_code == 408
        assert (await client.post('/process', headers=headers, json={'operation': 'check', 'payload': {}})).status_code == 200


@pytest.mark.parametrize('value', [[], None, {'operation': 'check', 'payload': []}] + [
    {'operation': 'check', 'payload': {}, 'timeout_seconds': value}
    for value in (None, 'nan', 'inf', -1)])
async def test_processing_rejects_invalid_envelopes_without_running_parser(value, monkeypatch):
    import app.processing_server as server
    monkeypatch.setenv('PROCESSING_TOKEN', 'x' * 48)
    def forbidden(*args, **kwargs):
        pytest.fail('Invalid envelopes must not reach the parser')
    monkeypatch.setattr(server, 'local_process', forbidden)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url='http://worker') as client:
        response = await client.post('/process', headers={'Authorization': 'Bearer ' + 'x' * 48}, json=value)
        assert response.status_code == 422


def test_native_subprocess_cannot_open_ipv4_or_ipv6_sockets():
    script = '''
import errno,socket
from app.services.processing_security import restrict_network
restrict_network()
for family in (socket.AF_INET,socket.AF_INET6):
    try: socket.socket(family,socket.SOCK_STREAM)
    except PermissionError as exc: assert exc.errno==errno.EPERM
    else: raise AssertionError('Network socket was allowed')
socket.socket(socket.AF_UNIX).close()
print('blocked')
'''
    result = subprocess.run([sys.executable, '-c', script], capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'blocked'


def test_native_deadline_kills_the_process_group_and_releases_slot(tmp_path, monkeypatch):
    import app.services.processing as processing
    original = subprocess.Popen
    pid_file = tmp_path / 'grandchild'
    script = ("import subprocess,sys,time;from pathlib import Path;"
              "child=subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
              f"Path({str(pid_file)!r}).write_text(str(child.pid));time.sleep(30)")
    monkeypatch.setattr(processing.subprocess, 'Popen', lambda args, **kw: original([sys.executable, '-c', script], **kw))
    started = time.monotonic()
    with pytest.raises(ProcessingError, match='time limit'):
        local_process({'operation': 'reference', 'payload': {}}, timeout=0.5)
    assert time.monotonic() - started < 5
    pid = int(pid_file.read_text())
    stat = Path(f'/proc/{pid}/stat')
    for _ in range(100):
        try:
            state = stat.read_text().split()[2]
        except (FileNotFoundError, ProcessLookupError):
            # The kernel can reap the process before or during the procfs read.
            break
        if state == 'Z':
            break
        time.sleep(0.01)
    else:
        pytest.fail('Descendant was left running')
    monkeypatch.undo()
    assert local_process({'operation': 'unsupported', 'payload': {}}, timeout=10)['ok'] is False


def synthetic_pdf(*, pages=1, text_chars=0):
    writer = PdfWriter()
    for _ in range(pages):
        page = writer.add_blank_page(100, 100)
        if text_chars:
            font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
            page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(b'BT /F1 12 Tf (' + b'A' * text_chars + b') Tj ET')
            page[NameObject('/Contents')] = writer._add_object(stream.flate_encode())
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


@pytest.mark.parametrize('payload', [synthetic_pdf(pages=31), synthetic_pdf(text_chars=524288), synthetic_pdf(text_chars=9_000_000)])
def test_reference_pdf_page_text_and_decompression_budgets(tmp_path, payload):
    library = ReferenceCVLibrary(tmp_path / 'references')
    record = library.upload('synthetic.pdf', payload)
    assert record['status'] == 'error'
    assert 'limit' in record['error'] or 'invalid' in record['error']


def test_reference_library_has_a_count_quota_before_writing(tmp_path):
    library = ReferenceCVLibrary(tmp_path / 'references')
    for index in range(20):
        (library.directory / f'{index}.pdf').write_bytes(b'%PDF-1.4 synthetic')
    with pytest.raises(ValueError, match='quota'):
        library.upload('new.pdf', b'%PDF-1.4 synthetic')
    assert len(list(library.directory.glob('*.pdf'))) == 20


def test_ai_daily_budget_is_atomic_persistent_and_resets_next_utc_day(tmp_path, monkeypatch):
    import app.services.resource_budget as budget_module
    clock = [100 * 86400.0]
    monkeypatch.setattr(budget_module.time, 'time', lambda: clock[0])
    a = ResourceBudget(tmp_path, daily_calls=1)
    b = ResourceBudget(tmp_path, daily_calls=1)
    results = []
    def charge(budget):
        try:
            budget.charge()
            results.append('allowed')
        except AIProviderError:
            results.append('blocked')
    threads = [threading.Thread(target=charge, args=(budget,)) for budget in (a, b)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert sorted(results) == ['allowed', 'blocked']
    with pytest.raises(AIProviderError, match='daily'):
        ResourceBudget(tmp_path, daily_calls=1).charge()
    clock[0] += 86400
    b.charge()


async def test_two_accounts_share_the_real_ai_concurrency_limit(tmp_path):
    (tmp_path / 'owner').mkdir()
    (tmp_path / 'demo').mkdir()
    owner = ResourceBudget(tmp_path / 'owner')
    demo = ResourceBudget(tmp_path / 'demo')
    demo.ai_slots = owner.ai_slots
    entered = asyncio.Event()
    async def second():
        async with demo.ai_call():
            entered.set()
    async with owner.ai_call():
        task = asyncio.create_task(second())
        await asyncio.sleep(0.02)
        assert not entered.is_set()
    await task
    assert entered.is_set()
    assert owner.path != demo.path


def test_queue_limit_cannot_be_bypassed_by_a_second_manager(tmp_path):
    manager = TaskManager(tmp_path, max_pending=2)
    for index in range(2):
        manager.create_task(TaskKind.TAILOR, {}, str(index))
    for instance in (manager, TaskManager(tmp_path, max_pending=2)):
        with pytest.raises(HTTPException) as error:
            instance.create_task(TaskKind.TAILOR, {}, 'excess')
        assert error.value.status_code == 429
    assert len(list(manager.tasks_dir.glob('*.json'))) == 2


@pytest.mark.parametrize('cleanup', [False, True])
def test_task_retention_preserves_live_work_and_saved_cv_drafts(tmp_path, cleanup):
    manager = TaskManager(tmp_path, auto_delete_history=True) if cleanup else TaskManager(tmp_path)
    (tmp_path / '.drafts').mkdir()
    folder = tmp_path / 'generated' / 'saved'
    folder.mkdir(parents=True)
    linked = 'a' * 32
    orphan = 'b' * 32
    for draft in (linked, orphan):
        (tmp_path / '.drafts' / (draft + '.json')).write_text('{}')
    (folder / 'metadata.json').write_text(json.dumps({'draft_id': linked}))
    for index in range(102):
        task = manager._create_task(TaskKind.TAILOR, {}, str(index))
        manager._queue.get_nowait()
        task.status = TaskStatus.COMPLETED
        task.result = {'draft_id': linked if index == 0 else orphan if index == 1 else ''}
        manager._save_task(task)
    new = manager.create_task(TaskKind.TAILOR, {}, 'active')
    assert len(list(manager.tasks_dir.glob('*.json'))) == (100 if cleanup else 103)
    assert manager.get_task(new.task_id).status == TaskStatus.QUEUED
    assert (tmp_path / '.drafts' / (linked + '.json')).exists()
    assert (tmp_path / '.drafts' / (orphan + '.json')).exists() is (not cleanup)
    assert json.loads((folder / 'metadata.json').read_text()) == {'draft_id': linked}


def test_history_cleanup_is_disabled_by_default_and_can_be_enabled(monkeypatch):
    from app.core.config import Settings
    monkeypatch.delenv('AUTO_DELETE_HISTORY', raising=False)
    assert Settings(_env_file=None).auto_delete_history is False
    monkeypatch.setenv('AUTO_DELETE_HISTORY', 'true')
    assert Settings(_env_file=None).auto_delete_history is True
    monkeypatch.setenv('AUTO_DELETE_HISTORY', 'false')
    assert Settings(_env_file=None).auto_delete_history is False


@pytest.mark.parametrize('cleanup', [False, True])
async def test_history_cleanup_setting_reaches_account_runtime(cleanup):
    from app.main import get_settings
    settings = get_settings().model_copy(update={'auto_delete_history': cleanup})
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        assert app.state.task_manager.auto_delete_history is cleanup


async def login(client):
    await client.get('/login')
    response = await client.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password', 'csrf_token': client.cookies.get('csrf_token')})
    assert response.status_code == 303


async def test_rejects_exhausted_requests_and_bad_csrf_before_reading_upload(monkeypatch):
    import app.main as main
    app = create_app(main.get_settings())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        await login(client)
        consumed = 0
        async def chunks():
            nonlocal consumed
            consumed += 1
            yield b'not-read'
        bad = await client.post('/profile/photo', content=chunks(), headers={'Content-Type': 'multipart/form-data; boundary=synthetic', 'X-CSRF-Token': 'bad'})
        assert bad.status_code == 403 and consumed == 0
        def blocked(key):
            raise HTTPException(429, 'Synthetic exhausted budget')
        monkeypatch.setattr(app.state.limiter, 'check', blocked)
        limited = await client.post('/profile/photo', content=chunks())
        assert limited.status_code == 429 and consumed == 0


async def test_chunked_and_declared_request_body_limits():
    import app.main as main
    app = create_app(main.get_settings())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        await login(client)
        token = client.cookies.get('csrf_token')
        consumed = 0
        async def chunks():
            nonlocal consumed
            for _ in range(128):
                consumed += 1
                yield b'x' * 8192
        response = await client.post('/settings/fallback', content=chunks(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        assert response.status_code == 413
        assert consumed <= 65
        consumed = 0
        response = await client.post('/profile/photo', content=chunks(), headers={'Content-Length': str(13 * 1024 * 1024), 'X-CSRF-Token': token})
        assert response.status_code == 413 and consumed == 0


async def test_slow_decoder_keeps_health_responsive_and_rejects_concurrent_updates(monkeypatch):
    import app.main as main
    app = create_app(main.get_settings())
    entered, release = threading.Event(), threading.Event()
    def slow(*args, **kwargs):
        entered.set()
        assert release.wait(3)
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        await login(client)
        monkeypatch.setattr(app.state.profile_photo, 'save', slow)
        pending = asyncio.create_task(client.post('/profile/photo', data={'csrf_token': client.cookies.get('csrf_token')}, files={'photo': ('synthetic.jpg', b'synthetic', 'image/jpeg')}))
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            assert (await asyncio.wait_for(client.get('/health'), 0.5)).status_code == 200
            assert (await client.post('/settings/fallback', data={'csrf_token': client.cookies.get('csrf_token')})).status_code == 429
        finally:
            release.set()
        assert (await pending).status_code == 303


async def test_storage_quota_does_not_prevent_cleanup_or_global_logout():
    import app.main as main
    app = create_app(main.get_settings())
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://testserver') as client:
        await login(client)
        app.state.resource_budget.disk_bytes = 64 * 1024 * 1024
        data = {'csrf_token': client.cookies.get('csrf_token')}
        assert (await client.post('/settings/fallback', data=data)).status_code == 507
        assert (await client.post('/diagnostics/clear', data=data)).status_code == 303
        assert (await client.post('/logout', data=data)).status_code == 303


async def test_ai_response_limit_stops_the_stream_before_consuming_all_chunks():
    count = 0
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal count
            for _ in range(20):
                count += 1
                yield b'x' * 262144
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=Stream()))) as client:
        with pytest.raises(ProviderResponseError, match='size limit'):
            await bounded_post(client, 'https://synthetic.example.test', json={})
    assert count == 9


async def test_processing_service_authenticates_before_reading_body(monkeypatch):
    from app.processing_server import app
    monkeypatch.setenv('PROCESSING_TOKEN', 'a' * 48)
    consumed = 0
    async def chunks():
        nonlocal consumed
        consumed += 1
        yield b'not-read'
    async with app.router.lifespan_context(app), httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://processor') as client:
        response = await client.post('/process', content=chunks(), headers={'Authorization': 'Bearer wrong'})
        assert response.status_code == 401 and consumed == 0


def test_production_workers_have_no_account_mounts_or_ai_secrets():
    manifest = json.loads(Path('deploy/k8s/production/processing.json').read_text())
    workers = [item for item in manifest['items'] if item['kind'] == 'Deployment']
    assert len(workers) == 2
    for worker in workers:
        spec = worker['spec']['template']['spec']
        assert not spec.get('hostNetwork', False)
        assert not spec['automountServiceAccountToken']
        assert spec['volumes'] == [{'name': 'scratch', 'emptyDir': {'sizeLimit': '256Mi'}}]
        container = spec['containers'][0]
        assert 'envFrom' not in container
        assert {entry['name'] for entry in container['env']} == {'PROCESSING_TOKEN', 'HOME', 'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE', 'PROCESSING_CONTAINER_ISOLATED'}
        assert container['securityContext']['readOnlyRootFilesystem']
        assert not container['securityContext']['allowPrivilegeEscalation']


def test_required_processing_cannot_silently_fall_back_to_the_application_process():
    import app.main as main
    settings = main.get_settings().model_copy(update={'processing_required': True})
    with pytest.raises(RuntimeError, match='isolated processing'):
        validate_auth_settings(settings)


def test_native_child_environment_excludes_application_secrets(monkeypatch):
    import app.services.processing as processing
    original = subprocess.Popen
    secret = 'synthetic-parent-secret-never-forward'
    monkeypatch.setenv('MALLOC_ARENA_MAX', '9999')
    for name in ('GEMINI_API_KEY', 'CSRF_SECRET', 'PROCESSING_TOKEN', 'DEMO_PROCESSING_TOKEN', 'APP_PASSWORD'):
        monkeypatch.setenv(name, secret)
    environments = []
    def capture(args, **kwargs):
        environments.append(kwargs['env'])
        return original(args, **kwargs)
    monkeypatch.setattr(processing.subprocess, 'Popen', capture)
    assert local_process({'operation': 'check', 'payload': {}}, timeout=10) == {'ok': True, 'result': {'protocol': 1, 'network_blocked': True}}
    assert len(environments) == 1
    assert environments[0]['MALLOC_ARENA_MAX'] == '2'
    assert secret not in json.dumps(environments)
    assert not {'GEMINI_API_KEY', 'CSRF_SECRET', 'PROCESSING_TOKEN', 'DEMO_PROCESSING_TOKEN', 'APP_PASSWORD'} & set(environments[0])


def test_configured_worker_failure_never_falls_back_to_local_processing(monkeypatch):
    import app.services.processing as processing
    original = httpx.Client
    def unavailable(request):
        raise httpx.ConnectError('Synthetic offline worker', request=request)
    monkeypatch.setattr(processing.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(unavailable), **kwargs))
    def forbidden(*args, **kwargs):
        pytest.fail('A configured service must never fall back to local processing')
    monkeypatch.setattr(processing, 'local_process', forbidden)
    token = processing.ENDPOINT.set(('http://synthetic-worker', 'a' * 48))
    try:
        with pytest.raises(ProcessingError, match='unavailable'):
            processing.process('check', {})
    finally:
        processing.ENDPOINT.reset(token)


def test_preview_cache_is_per_account_and_tracks_content_photo_and_profile(tmp_path, profile, resume_payload, monkeypatch):
    from app.models.resume import TailoredResume
    from app.services.pdf_generator import PDFGenerator
    calls = []
    def rendered(operation, payload):
        assert operation == 'preview'
        calls.append(payload)
        return f'<div>Synthetic preview {len(calls)}</div>'
    monkeypatch.setattr('app.services.processing.process', rendered)
    a = PDFGenerator(Path('templates'), Path('static'), tmp_path / 'owner')
    b = PDFGenerator(Path('templates'), Path('static'), tmp_path / 'demo')
    resume = TailoredResume.model_validate(resume_payload)
    first = a.render_preview(resume, profile)
    assert a.render_preview(resume, profile) == first
    assert b.render_preview(resume, profile) != first
    resume.professional_summary = 'Updated synthetic summary'
    changed = a.render_preview(resume, profile)
    assert changed != first
    profile = profile.model_copy(deep=True)
    profile.personal.name = 'Different Synthetic Identity'
    assert a.render_preview(resume, profile) != changed
    a.photo_store.directory.mkdir(parents=True)
    a.photo_store.jpg_path.write_bytes(b'synthetic-photo-cache-sentinel')
    a.render_preview(resume, profile)
    assert len(calls) == 5
    assert len(a._preview_cache) == 2


@pytest.mark.parametrize('encoding', ['gzip', 'br'])
async def test_ai_rejects_compressed_responses_without_consuming_the_body(encoding):
    consumed = False
    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            consumed = True
            yield b'not-read'
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={'content-encoding': encoding}, stream=Stream()))) as client:
        with pytest.raises(ProviderResponseError, match='Compressed'):
            await bounded_post(client, 'https://synthetic.example.test', json={})
    assert not consumed
