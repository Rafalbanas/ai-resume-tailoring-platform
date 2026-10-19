"""Role boundaries and routing must work without document libraries in the API."""
import json
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app import processing_server
from app.core.auth_boundary import validate_auth_settings
from app.core.config import Settings
from app.services import processing
from app.services.job_extractors.playwright_renderer import SafePlaywrightRenderer
from app.services.job_extractors.security import PublicUrlGuard
from scripts.runtime_requirements import BROWSER, DOCUMENTS, requirements


def test_api_imports_without_native_document_or_browser_packages():
    source = '''
import importlib.abc
import sys
class BlockNative(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'PIL','pillow_heif','docx','pypdf','pypdfium2','weasyprint','playwright'}:
            raise AssertionError('API imported a worker-only package: ' + fullname)
sys.meta_path.insert(0, BlockNative())
from app.main import app
assert app is not None
'''
    result = subprocess.run([sys.executable, '-c', source], capture_output=True, text=True, timeout=20,
                            cwd=Path(__file__).resolve().parents[1])
    assert result.returncode == 0, result.stderr


def test_role_pins_partition_the_existing_full_environment():
    sets = {role: set(requirements(role)) for role in ['api', 'documents', 'browser', 'full']}
    assert sets['documents'] | sets['browser'] == sets['full']
    assert sets['documents'] & sets['browser'] == sets['api']
    for role in ['api', 'browser']:
        assert not any(line.split('==')[0].lower() in DOCUMENTS for line in sets[role])
    assert not any(line.split('==')[0].lower() in BROWSER for line in sets['documents'])
    assert all('==' in line for lines in sets.values() for line in lines)


def test_document_and_browser_routing_use_independent_account_credentials(monkeypatch):
    seen = []
    original = httpx.Client
    def remote(request):
        seen.append((request.url.host, request.headers['authorization'], json.loads(request.content)['operation']))
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({'ok': True, 'result': 'synthetic result'}).encode()))
    monkeypatch.setattr(processing.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(remote), **kwargs))
    for account in ['owner', 'demo']:
        documents = processing.ENDPOINT.set((f'http://{account}-documents', account + '-document-token'))
        browser = processing.BROWSER_ENDPOINT.set((f'http://{account}-browser', account + '-browser-token'))
        try:
            assert processing.process('pdf', {}) == 'synthetic result'
            assert processing.process('browser', {}) == 'synthetic result'
        finally:
            processing.ENDPOINT.reset(documents)
            processing.BROWSER_ENDPOINT.reset(browser)
    assert seen == [(f'{account}-{role}', f'Bearer {account}-{kind}-token', operation)
                    for account in ['owner', 'demo']
                    for role, kind, operation in [('documents', 'document', 'pdf'), ('browser', 'browser', 'browser')]]


async def test_browser_renderer_uses_dedicated_remote_worker_without_playwright(monkeypatch):
    original = httpx.Client
    def remote(request):
        assert request.url.host == 'demo-browser'
        assert request.headers['authorization'] == 'Bearer demo-only'
        return httpx.Response(200, stream=httpx.ByteStream(json.dumps({'ok': True, 'result': {'url': 'https://example.com/job', 'html': '<p>Offer</p>'}}).encode()))
    monkeypatch.setattr(processing.httpx, 'Client', lambda **kwargs: original(transport=httpx.MockTransport(remote), **kwargs))
    token = processing.BROWSER_ENDPOINT.set(('http://demo-browser', 'demo-only'))
    document_token = processing.ENDPOINT.set(('', ''))
    try:
        result = await SafePlaywrightRenderer(PublicUrlGuard(), 5, 10000, 2).render('https://example.com/job')
        assert result.html == '<p>Offer</p>'
    finally:
        processing.BROWSER_ENDPOINT.reset(token)
        processing.ENDPOINT.reset(document_token)


def test_api_image_never_spawns_a_local_fallback(monkeypatch):
    monkeypatch.setenv('CVTAILOR_RUNTIME_ROLE', 'api')
    monkeypatch.delenv('PROCESSING_URL', raising=False)
    monkeypatch.delenv('BROWSER_PROCESSING_URL', raising=False)
    documents = processing.ENDPOINT.set(('', ''))
    browser = processing.BROWSER_ENDPOINT.set(('', ''))
    def forbidden(*args, **kwargs):
        pytest.fail('Slim API must not invoke a local parser')
    monkeypatch.setattr(processing, 'local_process', forbidden)
    try:
        for operation in ['pdf', 'browser']:
            with pytest.raises(processing.ProcessingError, match='remote processing'):
                processing.process(operation, {})
    finally:
        processing.ENDPOINT.reset(documents)
        processing.BROWSER_ENDPOINT.reset(browser)


@pytest.mark.parametrize('role,allowed,forbidden', [('documents', 'pdf', 'browser'), ('browser', 'browser', 'pdf')])
def test_worker_role_rejects_cross_role_operations_and_invalid_token(monkeypatch, role, allowed, forbidden):
    monkeypatch.setenv('PROCESSING_ROLE', role)
    monkeypatch.setenv('PROCESSING_TOKEN', 'a' * 48)
    monkeypatch.delenv('PROCESSING_CONTAINER_ISOLATED', raising=False)
    calls = []
    def child(value, **kwargs):
        calls.append(value['operation'])
        return {'ok': True, 'result': 'synthetic'}
    monkeypatch.setattr(processing_server, 'local_process', child)
    with TestClient(processing_server.app) as client:
        payload = {'operation': allowed, 'payload': {}, 'timeout_seconds': 5}
        assert client.post('/process', json=payload).status_code == 401
        headers = {'Authorization': 'Bearer ' + 'a' * 48}
        assert client.post('/process', headers=headers, json={**payload, 'operation': forbidden}).status_code == 400
        assert calls == []
        assert client.post('/process', headers=headers, json=payload).status_code == 200
        assert calls == [allowed]


def test_shared_accounts_require_distinct_browser_service_and_token(tmp_path):
    settings = Settings(_env_file=None, csrf_secret='synthetic-csrf-secret', demo_data_dir=tmp_path,
                        browser_processing_url='http://owner-browser', browser_processing_token='a' * 48)
    with pytest.raises(RuntimeError, match='independent browser'):
        validate_auth_settings(settings)
    settings.demo_browser_processing_url = 'http://demo-browser'
    settings.demo_browser_processing_token = 'b' * 48
    validate_auth_settings(settings)
    settings.demo_browser_processing_token = settings.browser_processing_token
    with pytest.raises(RuntimeError, match='independent browser'):
        validate_auth_settings(settings)


def test_compose_routes_accounts_to_role_images_without_worker_data_mounts():
    import yaml
    services = yaml.safe_load(Path('docker-compose.yml').read_text())['services']
    assert services['cv-tailor']['build']['target'] == 'api'
    assert services['cv-tailor']['volumes'] == ['./data:/app/data']
    env = services['cv-tailor']['environment']
    for role, prefix, ports in [('documents', 'processor', [18002, 18003]), ('browser', 'browser', [18004, 18005])]:
        for account, port in zip(['owner', 'demo'], ports, strict=True):
            worker = services[f'{prefix}-{account}']
            assert worker['build']['target'] == role
            assert 'volumes' not in worker and worker['read_only']
            assert worker['cap_drop'] == ['ALL']
            assert worker['ports'] == [f'127.0.0.1:{port}:8080']
            url_key = ('DEMO_' if account == 'demo' else '') + ('BROWSER_' if role == 'browser' else '') + 'PROCESSING_URL'
            assert env[url_key] == f'http://127.0.0.1:{port}'
    assert services['browser-demo']['profiles'] == ['demo']
    assert services['processor-demo']['profiles'] == ['demo']
