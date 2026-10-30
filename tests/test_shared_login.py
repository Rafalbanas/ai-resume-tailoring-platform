"""Two accounts, one URL: every protected operation uses the authenticated runtime."""
import asyncio
import base64
import json
import shutil

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.services.auth_store import AuthStore
from app.services.task_manager import TaskKind, TaskRecord, TaskStatus


@pytest.fixture
def shared_app(tmp_path):
    import app.main as main
    private = main.get_settings()
    demo_dir = tmp_path / 'shared-demo'
    demo_dir.mkdir()
    for name in ('master_profile.json', 'skills.json'):
        shutil.copyfile(private.data_dir / name, demo_dir / name)
    profile = json.loads((demo_dir / 'master_profile.json').read_text())
    profile['personal']['name'] = 'Synthetic Demo Sentinel'
    (demo_dir / 'master_profile.json').write_text(json.dumps(profile))
    (demo_dir / 'csrf.secret').write_text('independent-synthetic-demo-secret')
    AuthStore(demo_dir / 'auth.json', 'demo-tests', 'different-demo-password').initialize()
    for directory, label in ((private.data_dir, 'Synthetic Owner Sentinel'), (demo_dir, 'Synthetic Demo Sentinel')):
        path = directory / 'master_profile.json'
        value = json.loads(path.read_text())
        value['interests'] = [{'id': 'sentinel', 'name': label}]
        path.write_text(json.dumps(value))
    settings = private.model_copy(update={'demo_data_dir': demo_dir})
    return create_app(settings)


def sign_in(client, account):
    client.get('/login')
    return client.post('/login', data={
        'username': 'demo-tests' if account == 'demo' else 'audit-tests',
        'password': 'different-demo-password' if account == 'demo' else 'isolated-test-password',
        'csrf_token': client.cookies.get('csrf_token'),
    }, follow_redirects=False)


def runtimes(app):
    return app.state.accounts['owner'], app.state.accounts['demo']


@pytest.mark.parametrize('account', ['owner', 'demo'])
def test_same_url_selects_only_authenticated_accounts_data(shared_app, account, synthetic_download):
    with TestClient(shared_app) as client:
        assert sign_in(client, account).status_code == 303
        page = client.get('/profile')
        assert page.status_code == 200
        assert ('Synthetic Demo Sentinel' in page.text) == (account == 'demo')
        assert ('Synthetic Owner Sentinel' in page.text) == (account == 'owner')
        assert ('Demo — fictional data' in page.text) == (account == 'demo')
        owner, demo = runtimes(shared_app)
        for app, content in ((owner, b'%PDF private canary'), (demo, b'%PDF demo canary')):
            synthetic_download(app, 'same-id', content)
        expected = b'%PDF demo canary' if account == 'demo' else b'%PDF private canary'
        for query in ('', '?account=owner', '?account=demo', '?data_dir=../data', '?user=rafal'):
            response = client.get('/download/same-id/pdf' + query, headers={'X-Account': 'owner', 'X-Tenant': 'owner'})
            assert response.content == expected
        for path in ('/demo/profile', '/owner/profile', '/private/profile'):
            assert client.get(path, follow_redirects=False).status_code == 404


@pytest.mark.parametrize('account', ['owner', 'demo'])
def test_preview_and_draft_links_stay_in_their_account_before_exports_finish(shared_app, account, synthetic_download):
    from app.models.job import JobAnalysis
    from app.models.resume import WorkflowResponse

    with TestClient(shared_app) as client:
        owner, demo = runtimes(shared_app)
        source = owner if account == 'owner' else demo
        slug = '2026-10-21_synthetic_support_2'
        synthetic_download(source, slug, b'%PDF synthetic')
        # Match generation after save_application, before either export exists.
        folder = source.state.storage.application_folder(slug)
        (folder / 'resume.pdf').unlink()
        job, resume, _, _ = source.state.storage.load_application(slug)
        analysis = JobAnalysis.model_validate_json((folder / 'analysis.json').read_text())
        draft = source.state.storage.save_draft(job, WorkflowResponse(analysis=analysis, resume=resume))
        paths = (f'/preview/{slug}', f'/analysis/{draft}')
        for path in paths:
            assert client.get(path, follow_redirects=False).status_code == 303
        assert sign_in(client, account).status_code == 303
        for path in paths:
            assert client.get(path, follow_redirects=False).status_code == 200
        assert sign_in(client, 'demo' if account == 'owner' else 'owner').status_code == 303
        for path in paths:
            assert client.get(path, follow_redirects=False).status_code == 404
            assert client.get(path + f'?account={account}', headers={'X-Account': account},
                              follow_redirects=False).status_code == 404
        assert client.post(f'/generate/{draft}', data={
            'csrf_token': client.cookies.get('csrf_token'),
        }, follow_redirects=False).status_code == 404


@pytest.mark.parametrize('account', ['owner', 'demo'])
@pytest.mark.parametrize('status', list(TaskStatus))
def test_random_task_links_stay_in_their_account_at_every_stage(shared_app, account, status):
    from uuid import uuid4

    with TestClient(shared_app) as client:
        owner, demo = runtimes(shared_app)
        source = owner if account == 'owner' else demo
        task = TaskRecord(task_id=uuid4().hex, kind=TaskKind.TAILOR, idempotency_key='synthetic',
                          status=status, created_at='2026-10-21T00:00:00+00:00',
                          payload={'sentinel': 'synthetic account-private job'})
        # Persist a fixed state so no background worker can advance it mid-check.
        source.state.task_manager._save_task(task)
        paths = (f'/tasks/{task.task_id}', f'/tasks/{task.task_id}/view')
        for path in paths:
            assert client.get(path, follow_redirects=False).status_code == 303
        assert sign_in(client, account).status_code == 303
        assert client.get(paths[0]).json()['status'] == status.value
        assert client.get(paths[1], follow_redirects=False).status_code == 200
        assert sign_in(client, 'demo' if account == 'owner' else 'owner').status_code == 303
        for path in paths:
            assert client.get(path, follow_redirects=False).status_code == 404
            assert client.get(path + f'?account={account}', headers={'X-Account': account},
                              follow_redirects=False).status_code == 404


@pytest.mark.parametrize('account', ['owner', 'demo'])
def test_mutations_passwords_and_tasks_do_not_cross_accounts(shared_app, account):
    with TestClient(shared_app) as client:
        assert sign_in(client, account).status_code == 303
        owner, demo = runtimes(shared_app)
        target, other = (demo, owner) if account == 'demo' else (owner, demo)
        other_task = other.state.task_manager.create_task(kind=TaskKind.TAILOR, payload={'job': {}}, idempotency_key='other-only')
        assert client.get(f'/tasks/{other_task.task_id}', follow_redirects=False).status_code == 404
        response = client.post('/settings/fallback?account=owner', data={'enabled': 'off', 'csrf_token': client.cookies.get('csrf_token'), 'account': 'owner'})
        assert response.status_code == 200
        assert target.state.provider.fallback_enabled is False
        assert other.state.provider.fallback_enabled is True
        old_password = 'different-demo-password' if account == 'demo' else 'isolated-test-password'
        response = client.post('/account/password', data={
            'current_password': old_password, 'new_password': 'replacement-password-123',
            'repeat_password': 'replacement-password-123', 'csrf_token': client.cookies.get('csrf_token'),
            'account': 'owner' if account == 'demo' else 'demo',
        })
        assert response.status_code == 200
        assert target.state.auth_store.verify(target.state.auth_store.username, 'replacement-password-123')
        other_password = 'isolated-test-password' if account == 'demo' else 'different-demo-password'
        assert other.state.auth_store.verify(other.state.auth_store.username, other_password)
        assert client.get('/profile', follow_redirects=False).status_code == 303


def test_account_switch_revokes_previous_session_and_old_tab_csrf(shared_app):
    with TestClient(shared_app) as client:
        assert sign_in(client, 'owner').status_code == 303
        old_cookie = client.cookies.get('session')
        old_csrf = client.cookies.get('csrf_token')
        assert sign_in(client, 'demo').status_code == 303
        assert 'Synthetic Demo Sentinel' in client.get('/profile').text
        assert client.post('/settings/fallback', data={'csrf_token': old_csrf}).status_code == 403
        replay = TestClient(shared_app)
        replay.cookies.set('session', old_cookie)
        assert replay.get('/profile', follow_redirects=False).status_code == 303
        assert client.post('/logout', data={'csrf_token': client.cookies.get('csrf_token')}, follow_redirects=False).status_code == 303
        assert client.get('/profile', follow_redirects=False).status_code == 303


def test_tampering_account_claim_cannot_select_private_runtime(shared_app):
    with TestClient(shared_app) as client:
        assert sign_in(client, 'demo').status_code == 303
        cookie = client.cookies.get('session')
        payload, timestamp, signature = cookie.split('.')
        data = json.loads(base64.b64decode(payload))
        data['account'] = 'owner'
        forged = base64.b64encode(json.dumps(data).encode()).decode() + '.' + timestamp + '.' + signature
        client.cookies.clear()
        client.cookies.set('session', forged)
        assert client.get('/profile', follow_redirects=False).status_code == 303


def test_reset_inactive_account_does_not_revoke_active_account(shared_app):
    with TestClient(shared_app) as client:
        assert sign_in(client, 'demo').status_code == 303
        owner, demo = runtimes(shared_app)
        owner.state.auth_store.reset_password('replacement-password-123')
        assert client.get('/profile').status_code == 200
        demo.state.auth_store.reset_password('other-replacement-password-123')
        assert client.get('/profile', follow_redirects=False).status_code == 303


def test_overlapping_data_directories_are_rejected(shared_app):
    shared_app.state.settings_override.demo_data_dir = shared_app.state.settings_override.data_dir
    with pytest.raises(RuntimeError, match='non-overlapping'), TestClient(shared_app):
        pass


async def test_parallel_clients_and_background_jobs_keep_distinct_runtimes(shared_app):
    async with shared_app.router.lifespan_context(shared_app):
        transport = httpx.ASGITransport(app=shared_app)
        async with httpx.AsyncClient(transport=transport, base_url='http://testserver') as owner, \
                httpx.AsyncClient(transport=transport, base_url='http://testserver') as demo:
            async def authenticate(client, username, password):
                await client.get('/login')
                response = await client.post('/login', data={'username': username, 'password': password, 'csrf_token': client.cookies.get('csrf_token')})
                assert response.status_code == 303
            await asyncio.gather(authenticate(owner, 'audit-tests', 'isolated-test-password'), authenticate(demo, 'demo-tests', 'different-demo-password'))
            owner_page, demo_page = await asyncio.gather(owner.get('/profile'), demo.get('/profile'))
            assert 'Synthetic Owner Sentinel' in owner_page.text and 'Synthetic Demo Sentinel' not in owner_page.text
            assert 'Synthetic Demo Sentinel' in demo_page.text and 'Synthetic Owner Sentinel' not in demo_page.text
            owner_runtime, demo_runtime = runtimes(shared_app)
            assert owner_runtime.state.task_manager is not demo_runtime.state.task_manager
            assert owner_runtime.state.task_manager.tasks_dir != demo_runtime.state.task_manager.tasks_dir


def test_browser_shared_login_password_paste_and_account_bound_requests(shared_app, tmp_path):
    from playwright.sync_api import sync_playwright

    from tests.test_auth_boundary import browser_server
    with browser_server(shared_app, 'localhost') as url, sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        contexts = []
        try:
            pages = []
            for account, username, password in (
                ('owner', 'audit-tests', 'isolated-test-password'),
                ('demo', 'demo-tests', 'different-demo-password'),
            ):
                context = browser.new_context()
                contexts.append(context)
                context.grant_permissions(['clipboard-read', 'clipboard-write'], origin=url)
                page = context.new_page()
                page.goto(url + '/login')
                page.locator('[name=username]').fill(username)
                page.evaluate('(password) => navigator.clipboard.writeText(password)', password)
                field = page.locator('[name=password]')
                field.focus()
                field.press('Control+V')
                assert field.input_value() == password
                field.press('Enter')
                page.wait_for_url(url + '/')
                page.goto(url + '/profile')
                assert page.locator('.account-label').inner_text() == username
                marker = 'Synthetic Demo Sentinel' if account == 'demo' else 'Synthetic Owner Sentinel'
                assert marker in page.inner_text('body')
                page.screenshot(path=str(tmp_path / f'shared-{account}.png'))
                page.evaluate("""() => {
                    const script = document.createElement('script');
                    script.textContent = 'window.auditInjected = true';
                    document.head.appendChild(script);
                }""")
                assert page.evaluate('window.auditInjected === undefined')
                pages.append(page)
            demo = pages[1]
            # Store an XSS-shaped value through the real authenticated form.
            payload = '<img data-audit-xss src=x onerror="window.auditInjected=true">'
            demo.locator('form[action="/profile/interests/add"] [name=name]').fill(payload)
            demo.get_by_role('button', name='Add interest', exact=True).click()
            assert demo.locator('img[data-audit-xss]').count() == 0
            assert demo.evaluate('window.auditInjected === undefined')
            dialogs = []
            def confirm(dialog):
                dialogs.append(dialog.message)
                dialog.accept()
            demo.once('dialog', confirm)
            demo.locator('tr').filter(has_text=payload).get_by_role('button', name='Delete', exact=True).click()
            assert dialogs == ['Delete this interest?']
            result = demo.evaluate("""async () => {
                const token = document.querySelector('[name=csrf_token]').value;
                const response = await fetch('/settings/fallback?account=owner', {
                    method: 'POST', body: new URLSearchParams({csrf_token: token, enabled: 'off', account: 'owner'})
                });
                return response.status;
            }""")
            assert result == 200
            owner_runtime, demo_runtime = runtimes(shared_app)
            assert owner_runtime.state.provider.fallback_enabled
            assert not demo_runtime.state.provider.fallback_enabled
            # In one browser context, changing login invalidates stale forms in old tabs.
            old_csrf = demo.locator('[name=csrf_token]').first.get_attribute('value')
            switch = contexts[1].new_page()
            switch.goto(url + '/login')
            switch.locator('[name=username]').fill('audit-tests')
            switch.locator('[name=password]').fill('isolated-test-password')
            switch.get_by_role('button', name='Sign in', exact=True).click()
            switch.wait_for_url(url + '/')
            status = demo.evaluate("""async (token) => (await fetch('/settings/fallback', {
                method: 'POST', body: new URLSearchParams({csrf_token: token, enabled: 'off'})
            })).status""", old_csrf)
            assert status == 403
            assert owner_runtime.state.provider.fallback_enabled
        finally:
            for context in contexts:
                context.close()
            browser.close()


@pytest.mark.parametrize('alias', ['symlink-generated', 'hardlink-profile'])
def test_demo_cannot_alias_private_files(shared_app, alias):
    settings = shared_app.state.settings_override
    if alias == 'symlink-generated':
        (settings.demo_data_dir / 'generated').symlink_to(settings.data_dir / 'generated', target_is_directory=True)
    else:
        import os
        path = settings.demo_data_dir / 'master_profile.json'
        path.unlink()
        os.link(settings.master_profile_path, path)
    with pytest.raises(RuntimeError, match='runtime files'), TestClient(shared_app):
        pass


@pytest.mark.parametrize('account', ['owner', 'demo'])
def test_even_validly_signed_claim_cannot_reassign_a_session_to_another_account(shared_app, account):
    from app.main import ConfiguredSessionMiddleware
    with TestClient(shared_app) as client:
        assert sign_in(client, account).status_code == 303
        payload = client.cookies.get('session').split('.')[0]
        data = json.loads(base64.b64decode(payload))
        data['account'] = 'owner' if account == 'demo' else 'demo'
        middleware = ConfiguredSessionMiddleware(shared_app, settings=shared_app.state.settings)
        # Known synthetic signing key: test the database binding independently of signature checks.
        forged = middleware.signer.sign(base64.b64encode(json.dumps(data).encode())).decode()
        client.cookies.clear()
        client.cookies.set('session', forged)
        assert client.get('/profile', follow_redirects=False).status_code == 303
        assert client.get('/api/tasks/other', follow_redirects=False).status_code == 401


@pytest.mark.parametrize('account', ['owner', 'demo'])
async def test_logout_revokes_all_devices_only_for_active_account(shared_app, account):
    from contextlib import AsyncExitStack

    async with shared_app.router.lifespan_context(shared_app), AsyncExitStack() as stack:
        clients = [await stack.enter_async_context(httpx.AsyncClient(
            transport=httpx.ASGITransport(app=shared_app, client=(f'192.0.2.{i+1}', 12345)),
            base_url='http://testserver',
        )) for i in range(4)]

        async def sign_in(client, name):
            username, password = (('demo-tests', 'different-demo-password') if name == 'demo'
                                  else ('audit-tests', 'isolated-test-password'))
            await client.get('/login')
            response = await client.post('/login', data={
                'username': username, 'password': password, 'csrf_token': client.cookies.get('csrf_token'),
            })
            assert response.status_code == 303

        for client in clients[:3]:
            await sign_in(client, account)
        await sign_in(clients[3], 'owner' if account == 'demo' else 'demo')
        assert len({c.cookies.get('session') for c in clients[:3]}) == 3
        for client in clients:
            assert (await client.get('/profile')).status_code == 200
        # An invalid CSRF token must not log out any device.
        assert (await clients[0].post('/logout', data={'csrf_token': 'wrong'})).status_code == 403
        for client in clients:
            assert (await client.get('/profile')).status_code == 200
        response = await clients[0].post('/logout', data={'csrf_token': clients[0].cookies.get('csrf_token')})
        assert response.status_code == 303
        for client in clients[:3]:
            assert (await client.get('/profile')).status_code == 303
            assert (await client.post('/settings/fallback', data={
                'enabled': 'off', 'csrf_token': client.cookies.get('csrf_token'),
            })).status_code == 401
        assert (await clients[3].get('/profile')).status_code == 200
        # Revocation does not prevent a later, explicit fresh sign-in.
        await sign_in(clients[0], account)
        assert (await clients[0].get('/profile')).status_code == 200
        assert (await clients[1].get('/profile')).status_code == 303


async def test_demo_cannot_occupy_the_owners_reserved_native_processing_capacity(shared_app, monkeypatch):
    import threading
    entered, release = threading.Event(), threading.Event()
    async with shared_app.router.lifespan_context(shared_app):
        owner_app, demo_app = runtimes(shared_app)
        def parked(*args, **kwargs):
            entered.set()
            assert release.wait(3)
        monkeypatch.setattr(demo_app.state.profile_photo, 'save', parked)
        monkeypatch.setattr(owner_app.state.profile_photo, 'save', lambda *args, **kwargs: None)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=shared_app), base_url='http://testserver') as owner, \
                httpx.AsyncClient(transport=httpx.ASGITransport(app=shared_app), base_url='http://testserver') as demo:
            for client, username, password in ((owner, 'audit-tests', 'isolated-test-password'), (demo, 'demo-tests', 'different-demo-password')):
                await client.get('/login')
                assert (await client.post('/login', data={'username': username, 'password': password, 'csrf_token': client.cookies.get('csrf_token')})).status_code == 303
            pending = asyncio.create_task(demo.post('/profile/photo', data={'csrf_token': demo.cookies.get('csrf_token')}, files={'photo': ('synthetic.jpg', b'synthetic', 'image/jpeg')}))
            try:
                assert await asyncio.to_thread(entered.wait, 2)
                response = await asyncio.wait_for(owner.post('/profile/photo', data={'csrf_token': owner.cookies.get('csrf_token')}, files={'photo': ('synthetic.jpg', b'synthetic', 'image/jpeg')}), 1)
                assert response.status_code == 303
                assert (await owner.get('/health')).status_code == 200
            finally:
                release.set()
            assert (await pending).status_code == 303
