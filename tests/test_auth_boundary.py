"""Authentication regressions using independent, synthetic private/demo instances."""
import asyncio
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.core.auth_boundary import validate_auth_settings
from app.main import create_app
from app.services.auth_store import AuthStore
from app.services.login_limiter import LoginLimiter


@pytest.fixture
def instances(tmp_path):
    import app.main as main
    settings = main.get_settings()
    private = settings.model_copy(update={'base_url': 'https://private.example.test'})
    demo_data = tmp_path / 'demo'
    demo_data.mkdir()
    for name in ('master_profile.json', 'skills.json'):
        shutil.copyfile(settings.data_dir / name, demo_data / name)
    demo = settings.model_copy(update={
        'data_dir': demo_data, 'demo_mode': True,
        'base_url': 'https://demo.example.test', 'private_base_url': private.base_url,
        'app_username': 'demo-tests', 'app_password': 'different-demo-password',
        # Deliberately share the test signing secret: audience separation must still hold.
    })
    return create_app(private), create_app(demo)


def login(client, username='audit-tests', password='isolated-test-password'):
    client.get('/login')
    return client.post('/login', data={
        'username': username, 'password': password,
        'csrf_token': client.cookies.get('demo_csrf_token' if username == 'demo-tests' else 'csrf_token'),
    }, follow_redirects=False)


@pytest.mark.parametrize('direction', ['private-demo', 'demo-private'])
def test_credentials_sessions_and_private_artifacts_are_isolated(instances, direction):
    private, demo = instances
    with TestClient(private, base_url='https://private.example.test') as owner, \
            TestClient(demo, base_url='https://demo.example.test') as guest:
        assert login(owner).status_code == 303
        assert login(guest, 'demo-tests', 'different-demo-password').status_code == 303
        assert owner.get('/profile').status_code == guest.get('/profile').status_code == 200
        source, target = (owner, guest) if direction == 'private-demo' else (guest, owner)
        source_name, target_name = ('session', 'demo_session') if direction == 'private-demo' else ('demo_session', 'session')
        source_cookie = source.cookies.get(source_name)
        target.cookies.clear()
        target.cookies.set(target_name, source_cookie)
        for path in ('/profile', '/history', '/references', '/api/tasks/private-id', '/download/private-id/pdf'):
            assert target.get(path, follow_redirects=False).status_code in (303, 401)
        wrong_user, wrong_pass = ('audit-tests', 'isolated-test-password') if direction == 'private-demo' else ('demo-tests', 'different-demo-password')
        target.cookies.clear()
        target.get('/login')
        csrf_name = 'demo_csrf_token' if direction == 'private-demo' else 'csrf_token'
        response = target.post('/login', data={
            'username': wrong_user, 'password': wrong_pass, 'csrf_token': target.cookies.get(csrf_name),
        })
        assert response.status_code == 401
        # A route naming the other instance never selects its storage or account.
        assert source.get('/demo/profile' if direction == 'private-demo' else '/private/profile', follow_redirects=False).status_code == 404


@pytest.mark.parametrize('direction', ['private-demo', 'demo-private'])
def test_sibling_origin_cannot_mutate_even_with_valid_target_session(instances, direction):
    private, demo = instances
    target, target_url, foreign_url = (private, 'https://private.example.test', 'https://demo.example.test') if direction == 'demo-private' else (demo, 'https://demo.example.test', 'https://private.example.test')
    with TestClient(target, base_url=target_url) as client:
        demo_target = direction == 'private-demo'
        assert login(client, *('demo-tests', 'different-demo-password') if demo_target else ('audit-tests', 'isolated-test-password')).status_code == 303
        token = client.cookies.get('demo_csrf_token' if demo_target else 'csrf_token')
        response = client.post('/settings/fallback', data={'csrf_token': token}, headers={'Origin': foreign_url, 'Sec-Fetch-Site': 'same-site'})
        assert response.status_code == 403
        assert client.app.state.provider.fallback_enabled
        assert client.get('/profile', headers={'Origin': foreign_url}).headers.get('access-control-allow-origin') is None
        assert client.get('/profile', headers={'Host': foreign_url.split('://')[1]}).status_code == 400


@pytest.mark.parametrize('secret', ['', ' ', 'change-this-csrf-secret'])
def test_unsafe_secret_rejected(secret):
    import app.main as main
    with pytest.raises(RuntimeError, match='CSRF_SECRET'):
        validate_auth_settings(main.get_settings().model_copy(update={'csrf_secret': secret}))


@pytest.mark.parametrize('private_url', ['', 'https://demo.example.test', 'http://demo.example.test:9000'])
def test_demo_requires_an_independent_hostname(private_url):
    import app.main as main
    settings = main.get_settings().model_copy(update={
        'demo_mode': True, 'base_url': 'https://demo.example.test/demo', 'private_base_url': private_url,
    })
    with pytest.raises(RuntimeError, match='different hostname'):
        validate_auth_settings(settings)


def test_csrf_is_browser_bound_and_rotates_on_login(instances):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as first, \
            TestClient(private, base_url='https://private.example.test') as second:
        first.get('/login')
        old = first.cookies.get('csrf_token')
        second.get('/login')
        # A valid signed public token is insufficient when its session is different.
        response = second.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password', 'csrf_token': old}, headers={'Cookie': 'csrf_token=' + old + '; session=' + second.cookies.get('session')})
        assert response.status_code == 403
        response = first.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password', 'csrf_token': old}, follow_redirects=False)
        assert response.status_code == 303
        assert first.cookies.get('csrf_token') != old
        assert first.post('/logout', data={'csrf_token': old}).status_code == 403
        assert first.post('/logout', data={'csrf_token': first.cookies.get('csrf_token')}, follow_redirects=False).status_code == 303


def test_unicode_and_duplicate_fields_return_controlled_errors(instances):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        client.get('/login')
        token = client.cookies.get('csrf_token')
        assert client.post('/login', data={'username': 'żółw', 'password': 'wrong', 'csrf_token': token}).status_code == 401
        assert client.post('/login', data={'username': 'x', 'password': 'wrong', 'csrf_token': 'żółw'}).status_code == 403
        response = client.post('/login', content=f'username=x&username=audit-tests&password=wrong&csrf_token={token}', headers={'Content-Type': 'application/x-www-form-urlencoded'})
        assert response.status_code == 400


def test_login_size_limit_precedes_form_parsing(instances):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        assert client.post('/login', content=b'x' * 16385).status_code == 413
        def chunks():
            yield b'x' * 8000
            yield b'x' * 9000
        assert client.post('/login', content=chunks()).status_code == 413
        client.get('/login')
        assert client.post('/login', data={'username': 'x' * 151, 'password': 'wrong', 'csrf_token': client.cookies.get('csrf_token')}).status_code == 422


def test_limiter_is_shared_atomic_expiring_and_bounds_distinct_clients(tmp_path):
    path = tmp_path / 'sessions.sqlite3'
    first = LoginLimiter(path, limit=2, window=300, global_limit=3)
    second = LoginLimiter(path, limit=2, window=300, global_limit=3)
    first.check('one')
    second.check('one')
    with pytest.raises(HTTPException) as error:
        second.check('one')
    assert error.value.status_code == 429
    second.check('two')
    with pytest.raises(HTTPException):
        first.check('three')
    import sqlite3
    with sqlite3.connect(path) as db:
        assert db.execute('SELECT COUNT(*) FROM login_attempts').fetchone()[0] == 3
        db.execute('UPDATE login_attempts SET created = 0')
    first.check('one')
    def attempt(_):
        try:
            LoginLimiter(path, limit=2).check('concurrent')
            return True
        except HTTPException:
            return False
    with ThreadPoolExecutor(max_workers=8) as executor:
        assert sum(executor.map(attempt, range(8))) == 2


def test_reset_race_does_not_grant_a_session_for_new_credentials(instances, monkeypatch):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        store = private.state.auth_store
        original = store.verify_with_version
        def verify_then_reset(username, password):
            version = original(username, password)
            AuthStore(store.path).reset_password('replacement-password-123')
            return version
        monkeypatch.setattr(store, 'verify_with_version', verify_then_reset)
        assert login(client).status_code == 303
        assert client.get('/profile', follow_redirects=False).status_code == 303


async def test_password_verification_does_not_block_event_loop(instances, monkeypatch):
    private, _ = instances
    started, release = threading.Event(), threading.Event()
    async with private.router.lifespan_context(private):
        original = private.state.auth_store.verify_with_version
        def slow_verify(username, password):
            started.set()
            assert release.wait(5), 'Test did not release the worker'
            return original(username, password)
        monkeypatch.setattr(private.state.auth_store, 'verify_with_version', slow_verify)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=private), base_url='https://private.example.test') as client:
            await client.get('/login')
            request = asyncio.create_task(client.post('/login', data={'username': 'wrong', 'password': 'wrong', 'csrf_token': client.cookies.get('csrf_token')}))
            try:
                for _ in range(100):
                    if started.is_set():
                        break
                    await asyncio.sleep(0.01)
                assert started.is_set()
                assert (await asyncio.wait_for(client.get('/health'), 1)).status_code == 200
            finally:
                release.set()
                await request


def test_login_csp_and_paste_are_preserved(instances):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        page = client.get('/login?next=https://attacker.invalid&error=%3Cscript%3Ealert(1)%3C/script%3E')
        assert 'attacker.invalid' not in page.text
        assert '<script>alert(1)</script>' not in page.text
        policy = page.headers['Content-Security-Policy']
        assert "form-action 'self'" in policy and "frame-ancestors 'none'" in policy
        assert "'unsafe-inline'" not in policy.split("script-src", 1)[1].split(";", 1)[0]
        assert 'autocomplete="current-password"' in page.text
        assert 'onpaste' not in page.text


@contextmanager
def browser_server(application, hostname):
    import socket
    import time

    import uvicorn
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    port = sock.getsockname()[1]
    url = f'http://{hostname}:{port}'
    application.state.settings_override.base_url = url
    server = uvicorn.Server(uvicorn.Config(application, log_config=None, log_level='warning', proxy_headers=False))
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            if not thread.is_alive() or time.monotonic() > deadline:
                raise RuntimeError('Synthetic browser server failed to start')
            time.sleep(0.01)
        yield url
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        sock.close()


def test_real_browser_isolates_accounts_and_preserves_password_paste(instances):
    from playwright.sync_api import sync_playwright

    private, demo = instances
    with browser_server(private, 'private.localhost') as private_url:
        demo.state.settings_override.private_base_url = private_url
        with browser_server(demo, 'demo.localhost') as demo_url, sync_playwright() as playwright:
            browser = playwright.chromium.launch(args=['--no-sandbox'])
            context = browser.new_context()
            try:
                pages = []
                for url, username, password in (
                    (private_url, 'audit-tests', 'isolated-test-password'),
                    (demo_url, 'demo-tests', 'different-demo-password'),
                ):
                    context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url)
                    page = context.new_page()
                    page.goto(url + '/login')
                    page.evaluate("""() => {
                        const script = document.createElement('script');
                        script.textContent = 'window.auditInjected = true';
                        document.head.appendChild(script);
                    }""")
                    assert page.evaluate('window.auditInjected === undefined')
                    page.locator('[name=username]').fill(username)
                    page.evaluate('(password) => navigator.clipboard.writeText(password)', password)
                    field = page.locator('[name=password]')
                    field.focus()
                    field.press('Control+V')
                    assert field.input_value() == password
                    with page.expect_response(lambda response: response.request.method == 'POST' and response.url.endswith('/login')) as submitted:
                        page.get_by_role('button', name='Sign in', exact=True).click()
                    assert submitted.value.status == 303, (submitted.value.text(), {k: v for k, v in submitted.value.request.headers.items() if k in ("origin", "content-length", "sec-fetch-site", "host")})
                    page.wait_for_url(url + '/')
                    pages.append(page)
                for source, target in ((pages[0], demo_url), (pages[1], private_url)):
                    result = source.evaluate("""async (url) => {
                        try {
                            await fetch(url + '/profile', {credentials: 'include'});
                            return 'unexpected-access';
                        } catch (_) { return 'blocked'; }
                    }""", target)
                    assert result == 'blocked'
                # Even with the target's CSRF value, the browser's actual Origin blocks mutation.
                for source, target, app, cookie_name in (
                    (pages[0], demo_url, demo, 'demo_csrf_token'),
                    (pages[1], private_url, private, 'csrf_token'),
                ):
                    csrf = next(cookie['value'] for cookie in context.cookies(target) if cookie['name'] == cookie_name)
                    source.evaluate("""async ({url, token}) => {
                        try {
                            await fetch(url + '/settings/fallback', {
                                method: 'POST', credentials: 'include',
                                body: new URLSearchParams({csrf_token: token, enabled: 'off'})
                            });
                        } catch (_) {}
                    }""", {'url': target, 'token': csrf})
                    assert app.state.provider.fallback_enabled
            finally:
                context.close()
                browser.close()


@pytest.mark.parametrize('payload', ["' OR '1'='1' --", "admin'--", "' UNION SELECT NULL --", '" OR 1=1 --', '{"$ne":null}', '<script>alert(1)</script>'])
def test_injection_does_not_authenticate(instances, payload):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        for username, password in ((payload, 'isolated-test-password'), ('audit-tests', payload)):
            assert login(client, username, password).status_code == 401
            assert client.get('/profile', follow_redirects=False).status_code == 303


@pytest.mark.parametrize('direction', ['private-demo', 'demo-private'])
def test_artifacts_and_reset_stay_in_their_own_instance(instances, direction, synthetic_download):
    private, demo = instances
    with TestClient(private, base_url='https://private.example.test') as owner, \
            TestClient(demo, base_url='https://demo.example.test') as guest:
        assert login(owner).status_code == 303
        assert login(guest, 'demo-tests', 'different-demo-password').status_code == 303
        for app, client, content in ((private, owner, b'%PDF synthetic private'), (demo, guest, b'%PDF synthetic demo')):
            synthetic_download(app, 'same-id', content)
            assert client.get('/download/same-id/pdf').content == content
        changed, revoked, unaffected = (private, owner, guest) if direction == 'private-demo' else (demo, guest, owner)
        changed.state.auth_store.reset_password('replacement-test-password')
        assert revoked.get('/profile', follow_redirects=False).status_code == 303
        assert unaffected.get('/profile', follow_redirects=False).status_code == 200


@pytest.mark.parametrize('site,expected', [(None, 403), ('cross-site', 403), ('same-site', 403), ('same-origin', 303)])
def test_null_origin_requires_browser_same_origin_metadata(instances, site, expected):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        client.get('/login')
        headers = {'Origin': 'null'}
        if site:
            headers['Sec-Fetch-Site'] = site
        response = client.post('/login', headers=headers, data={
            'username': 'audit-tests', 'password': 'isolated-test-password',
            'csrf_token': client.cookies.get('csrf_token'),
        }, follow_redirects=False)
        assert response.status_code == expected


@pytest.mark.parametrize('header,value', [('Host', 'private.example.test'), ('Origin', 'https://private.example.test'), ('Content-Length', '0')])
def test_ambiguous_security_headers_are_rejected(instances, header, value):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        response = client.post('/login', headers=[(header, value), (header, value)], content=b'')
        assert response.status_code == 400


def test_password_change_rejects_duplicate_fields(instances):
    private, _ = instances
    with TestClient(private, base_url='https://private.example.test') as client:
        assert login(client).status_code == 303
        token = client.cookies.get('csrf_token')
        response = client.post('/account/password', content=(
            f'current_password=isolated-test-password&new_password=replacement-password-123'
            f'&new_password=second-password-456&repeat_password=replacement-password-123&csrf_token={token}'
        ), headers={'Content-Type': 'application/x-www-form-urlencoded'})
        assert response.status_code == 400
        assert private.state.auth_store.verify('audit-tests', 'isolated-test-password')


@pytest.mark.parametrize('client_ip', ['198.51.100.10', '127.0.0.1'])
async def test_default_proxy_policy_does_not_allow_spoofing_login_budget(instances, client_ip):
    import json
    from pathlib import Path

    from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
    private, _ = instances
    command = next(line[4:] for line in (Path(__file__).resolve().parents[1] / 'Dockerfile').read_text().splitlines() if line.startswith('CMD '))
    trusted = next(arg.split('=', 1)[1] for arg in json.loads(command) if arg.startswith('--forwarded-allow-ips='))
    proxy = ProxyHeadersMiddleware(private, trusted_hosts=trusted)
    async with private.router.lifespan_context(private):
        transport = httpx.ASGITransport(app=proxy, client=(client_ip, 1234))
        async with httpx.AsyncClient(transport=transport, base_url='https://private.example.test') as client:
            await client.get('/login')
            token = client.cookies.get('csrf_token')
            for number in range(6):
                forwarded = f'203.0.113.{number}'
                if client_ip == '127.0.0.1':
                    # The trusted proxy appends the actual peer after untrusted input.
                    forwarded += ', 198.51.100.10'
                response = await client.post('/login', headers={'X-Forwarded-For': forwarded}, data={
                    'username': 'wrong', 'password': 'wrong', 'csrf_token': token,
                })
                assert response.status_code == (401 if number < 5 else 429)


@pytest.mark.parametrize('path', ['/health', '/static/app.js'])
async def test_public_read_only_routes_reject_post_without_reading_body(instances, path):
    private, _ = instances
    async def forbidden_body():
        raise AssertionError('A public read-only route must not read a POST body')
        yield b''
    async with private.router.lifespan_context(private):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=private), base_url='https://private.example.test') as client:
            response = await client.post(path, content=forbidden_body(), headers={'Content-Type': 'application/x-www-form-urlencoded'})
            assert response.status_code == 405
