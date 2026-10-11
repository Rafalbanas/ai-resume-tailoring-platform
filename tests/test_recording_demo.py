from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.ai_provider import GeminiAuthError, ProviderUnavailableError
from app.services.resilient_provider import ResilientAIProvider
from tests.test_provider_fallback import job, sample_workflow_response


def sign_in(client):
    client.get('/login')
    return client.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password',
                                     'csrf_token': client.cookies.get('csrf_token')}, follow_redirects=False)


def test_session_lifecycle():
    with TestClient(app) as client:
        assert client.get('/', follow_redirects=False).status_code == 303
        assert client.get('/health').json() == {'status': 'ok'}
        assert client.get('/health/profile', follow_redirects=False).status_code == 401
        assert client.get('/', auth=('audit-tests', 'isolated-test-password'), follow_redirects=False).status_code == 303
        client.get('/login')
        assert client.post('/login', data={'username': 'audit-tests', 'password': 'bad'}).status_code == 403
        assert client.post('/login', data={'username': 'wrong', 'password': 'bad',
                                          'csrf_token': client.cookies.get('csrf_token')}).status_code == 401
        result = sign_in(client)
        assert result.status_code == 303
        assert 'HttpOnly' in result.headers['set-cookie'] and 'SameSite=strict' in result.headers['set-cookie']
        assert client.get('/').status_code == 200
        folder = app.state.storage.generated_dir / 'synthetic-download'
        folder.mkdir()
        (folder / 'resume.pdf').write_bytes(b'%PDF synthetic test')
        assert client.get('/download/synthetic-download/pdf').status_code == 200
        old = client.cookies.get('session')
        assert client.post('/logout').status_code == 403
        assert client.post('/settings/fallback', data={'csrf_token': client.cookies.get('csrf_token')}).status_code == 200
        assert app.state.provider.fallback_enabled is False
        assert client.post('/logout', data={'csrf_token': client.cookies.get('csrf_token')}, follow_redirects=False).status_code == 303
        assert not client.cookies.get('session')
        client.cookies.set('session', old)
        for path in ['/', '/profile', '/history', '/references', '/skills', '/api/tasks/test', '/download/synthetic-download/pdf']:
            assert client.get(path, follow_redirects=False).status_code in {303, 401}
        sign_in(client)
        with app.state.sessions.connect() as db:
            db.execute('UPDATE sessions SET expires = 0')
        assert client.get('/', follow_redirects=False).status_code == 303


def test_login_limit():
    with TestClient(app) as client:
        client.get('/login')
        data = {'username': 'wrong', 'password': 'wrong', 'csrf_token': client.cookies.get('csrf_token')}
        for _ in range(5):
            assert client.post('/login', data=data).status_code == 401
        assert client.post('/login', data=data).status_code == 429


@pytest.mark.asyncio
@pytest.mark.parametrize('choice', ['auto', 'ollama', 'gemini'])
@pytest.mark.parametrize('enabled', [True, False])
@pytest.mark.parametrize('error', [ProviderUnavailableError('failure'), TimeoutError('timeout'), GeminiAuthError('auth')])
async def test_all_provider_policies(profile, choice, enabled, error):
    primary = 'gemini' if choice == 'gemini' else 'ollama'
    secondary = 'ollama' if primary == 'gemini' else 'gemini'
    class Provider:
        def __init__(self, name, fail=False):
            self.name, self.model = name, name + '-mock'
            self.tailor = AsyncMock(side_effect=error) if fail else AsyncMock(return_value=sample_workflow_response(name, self.model))
    providers = {primary: Provider(primary, True), secondary: Provider(secondary)}
    router = ResilientAIProvider(providers)
    router.fallback_enabled = enabled
    if enabled:
        result = await router.tailor(job(), profile, choice)
        assert result.provider_used == secondary and result.fallback_used
        assert result.model_used == secondary + '-mock'
        providers[secondary].tailor.assert_awaited_once()
    else:
        with pytest.raises((ProviderUnavailableError, GeminiAuthError)):
            await router.tailor(job(), profile, choice)
        providers[secondary].tailor.assert_not_awaited()


def test_settings_are_instance_local(tmp_path):
    first, second = ResilientAIProvider({}), ResilientAIProvider({})
    first.settings_path = tmp_path / 'first.json'
    second.settings_path = tmp_path / 'second.json'
    first.save_settings(False)
    second.load_settings()
    assert second.fallback_enabled
    restored = ResilientAIProvider({})
    restored.settings_path = first.settings_path
    restored.load_settings()
    assert not restored.fallback_enabled


def test_secure_cookie_and_credential_migration(monkeypatch):
    import app.main as main_module
    settings = main_module.get_settings()
    settings.base_url = "https://testserver"
    monkeypatch.setattr(app, "middleware_stack", None)
    with TestClient(app, base_url="https://testserver") as client:
        before = app.state.auth_store.path.read_bytes()
        app.state.auth_store.initialize()
        assert app.state.auth_store.path.read_bytes() == before
        response = sign_in(client)
        assert response.status_code == 303 and "Secure" in response.headers["set-cookie"]
        app.state.auth_store.reset_password("new-test-password-123456")
        assert client.get("/", follow_redirects=False).status_code == 303


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_unconfigured_gemini_respects_switch(profile, enabled):
    class Provider:
        name, model, api_key = "gemini", "gemini-mock", ""
        tailor = AsyncMock()
    class Fallback:
        name, model = "ollama", "ollama-mock"
        tailor = AsyncMock(return_value=sample_workflow_response("ollama", "ollama-mock"))
    fallback = Fallback()
    fallback.tailor.reset_mock()
    router = ResilientAIProvider({"gemini": Provider(), "ollama": fallback})
    router.fallback_enabled = enabled
    if enabled:
        result = await router.tailor(job(), profile, "gemini")
        assert result.fallback_used and result.provider_used == "ollama" and result.model_used == "ollama-mock"
    else:
        with pytest.raises(GeminiAuthError):
            await router.tailor(job(), profile, "gemini")
        fallback.tailor.assert_not_awaited()


def test_multipart_upload_and_settings_require_session_and_csrf():
    import io

    from docx import Document
    document = Document()
    document.add_paragraph('Alex Example: fictional reference CV for a synthetic test.')
    buffer = io.BytesIO()
    document.save(buffer)
    with TestClient(app) as client:
        client.get('/login')
        token = client.cookies.get('csrf_token')
        assert client.post('/settings/fallback', data={'enabled': 'off', 'csrf_token': token},
                           follow_redirects=False).status_code == 401
        assert client.post('/references/upload', files={'files': ('example.docx', buffer.getvalue())},
                           data={'csrf_token': token}, follow_redirects=False).status_code == 401
        sign_in(client)
        assert client.post('/settings/fallback', data={'enabled': 'off'}, follow_redirects=False).status_code == 403
        result = client.post('/references/upload', files={'files': ('example.docx', buffer.getvalue())},
                             data={'csrf_token': client.cookies.get('csrf_token')}, follow_redirects=False)
        assert result.status_code == 303
        assert len(app.state.reference_library.list()) == 1


def test_https_proxy_scheme_sets_secure_even_with_http_base_url():
    with TestClient(app, base_url="https://testserver") as client:
        assert app.state.settings.base_url.startswith("http:")
        response = sign_in(client)
        assert response.status_code == 303
        assert all("secure" in cookie.lower() for cookie in response.headers.get_list("set-cookie"))


def test_demo_prefix_and_cookie_isolation(monkeypatch):
    import app.main as main_module
    settings = main_module.get_settings()
    settings.demo_mode = True
    settings.app_root_path = '/demo'
    settings.base_url = 'https://cv.banas.dev/demo'
    with TestClient(app, base_url='https://cv.banas.dev', root_path='/demo') as client:
        client.cookies.set('session', 'private-session')
        client.cookies.set('csrf_token', 'private-csrf')
        page = client.get('/demo/login')
        assert page.status_code == 200
        assert 'action="/demo/login"' in page.text
        assert '/demo/static/app.js' in page.text
        assert client.get('/demo/', follow_redirects=False).headers['location'] == '/demo/login'
        token = client.cookies.get('demo_csrf_token')
        result = client.post('/demo/login', data={'username': 'audit-tests', 'password': 'isolated-test-password',
                                                  'csrf_token': token}, follow_redirects=False)
        assert result.status_code == 303 and result.headers['location'] == '/demo/'
        assert client.cookies.get('demo_session')
        assert client.cookies.get('session') == 'private-session'
        assert any('Path=/demo' in h for h in result.headers.get_list('set-cookie'))
        page = client.get('/demo/')
        assert page.status_code == 200 and 'action="/demo/logout"' in page.text
        assert 'Demo — fictional data' in page.text
        assert client.post('/demo/logout', data={'csrf_token': token}, follow_redirects=False).headers['location'] == '/demo/login'
        assert client.cookies.get('session') == 'private-session'
        assert client.cookies.get('csrf_token') == 'private-csrf'
        assert client.get('/demo/download/test/pdf', follow_redirects=False).status_code == 401
