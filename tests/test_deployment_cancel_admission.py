"""The deployment exception is exact and never substitutes for downstream auth."""
import fcntl
import os
from contextlib import contextmanager

import httpx
import pytest
from starlette.responses import JSONResponse

from deploy.k8s.production.runtime import DeploymentAdmission

ID = 'abcdef1234567890abcdef1234567890'
PATHS = [f'/api/v1/batches/{ID}/cancel', f'/queue/tasks/{ID}/cancel-batch']


@contextmanager
def locked(root):
    descriptor = os.open(root / '.deployment-admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(descriptor)


async def protected_app(scope, receive, send):
    headers = dict(scope['headers'])
    status = 200
    if scope['method'] != 'GET':
        if b'authorization' not in headers:
            status = 401
        elif headers.get(b'x-test-csrf') != b'true':
            status = 403
    await JSONResponse({'downstream': True}, status_code=status)(scope, receive, send)


@pytest.mark.asyncio
@pytest.mark.parametrize('root', ['', '/workspace'])
@pytest.mark.parametrize('path', PATHS)
async def test_exact_cancel_paths_preserve_downstream_auth_csrf(tmp_path, root, path):
    transport = httpx.ASGITransport(app=DeploymentAdmission(protected_app, tmp_path), root_path=root)
    with locked(tmp_path):
        async with httpx.AsyncClient(transport=transport, base_url='http://test') as client:
            assert (await client.post(root + path)).status_code == 401
            assert (await client.post(root + path, headers={'Authorization': 'synthetic'})).status_code == 403
            assert (await client.post(root + path, headers={
                'Authorization': 'synthetic', 'X-Test-CSRF': 'true'})).status_code == 200
            assert (await client.get('/health')).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize('method,path', [
    *[(method, path) for method in ['PUT', 'PATCH', 'DELETE'] for path in PATHS],
    *[('POST', path + suffix) for path in PATHS for suffix in ['/', '/extra', '.json']],
    *[('POST', prefix + path) for path in PATHS for prefix in ['/demo', '/other']],
    *[('POST', path.replace(ID, bad)) for path in PATHS for bad in ['a' * 31, 'a' * 33, 'A' * 32, 'g' * 32]],
    ('POST', '/analyze'), ('POST', f'/tasks/{ID}/retry'), ('POST', f'/queue/tasks/{ID}/reject'),
])
async def test_other_mutations_stay_blocked(tmp_path, method, path):
    with locked(tmp_path):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(
                app=DeploymentAdmission(protected_app, tmp_path)), base_url='http://test') as client:
            response = await client.request(method, path, headers={
                'Authorization': 'synthetic', 'X-Test-CSRF': 'true'})
            assert response.status_code == 503
            assert response.json()['code'] == 'deployment_in_progress'
            assert response.headers['retry-after'] == '30'
            assert response.headers['cache-control'] == 'no-store'


@pytest.mark.asyncio
async def test_mutations_without_lock_are_not_restricted(tmp_path):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(
            app=DeploymentAdmission(protected_app, tmp_path)), base_url='http://test') as client:
        assert (await client.post('/analyze', headers={
            'Authorization': 'synthetic', 'X-Test-CSRF': 'true'})).status_code == 200
