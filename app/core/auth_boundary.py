"""Reject foreign origins and bound authentication requests before form parsing."""
from urllib.parse import urlsplit

from fastapi import HTTPException
from starlette.concurrency import run_in_threadpool
from starlette.responses import JSONResponse


def origin(url):
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'} or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('A valid HTTP(S) origin is required')
    return parsed.scheme, parsed.hostname.lower(), parsed.port or (443 if parsed.scheme == 'https' else 80)


def validate_auth_settings(settings, shared_account=False):
    if not settings.csrf_secret.strip() or settings.csrf_secret == 'change-this-csrf-secret':
        raise RuntimeError('Configure a non-default CSRF_SECRET before starting the application')
    if settings.processing_required and not settings.processing_url:
        raise RuntimeError('An isolated processing service is required for this deployment')
    if settings.processing_url and len(settings.processing_token) < 32:
        raise RuntimeError('A PROCESSING_TOKEN of at least 32 characters is required')
    if settings.demo_data_dir is not None and settings.processing_url and (not settings.demo_processing_url or not settings.demo_processing_token or settings.demo_processing_url == settings.processing_url or settings.demo_processing_token == settings.processing_token or len(settings.demo_processing_token) < 32):
        raise RuntimeError('Shared accounts require independent processing services and tokens')
    own = origin(settings.base_url)
    if settings.demo_mode and not shared_account:
        if not settings.private_base_url or origin(settings.private_base_url)[1] == own[1]:
            raise RuntimeError('Demo requires PRIVATE_BASE_URL and a different hostname from the private application')


class AuthBoundaryMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        settings = scope['app'].state.settings
        path = scope['path']
        root = scope.get('root_path', '')
        if root and (path == root or path.startswith(root + '/')):
            path = path[len(root):] or '/'
        headers = dict(scope['headers'])
        unsafe = scope['method'] in {'POST', 'PUT', 'PATCH', 'DELETE'}
        expected = origin(settings.base_url)
        host = headers.get(b'host', b'').decode('latin1')
        try:
            if (path == '/health' or path.startswith('/static/')) and scope['method'] not in {'GET', 'HEAD'}:
                raise HTTPException(405, 'Method not allowed', headers={'Allow': 'GET, HEAD'})
            for name in (b'host', b'origin', b'content-length'):
                if sum(key == name for key, _ in scope['headers']) > 1:
                    raise HTTPException(400, 'Duplicate request headers')
            actual = origin(scope.get('scheme', 'http') + '://' + host)
            # Keep loopback health probes independent of the public hostname.
            if path != '/health' and expected[0] == 'https' and actual != expected:
                raise HTTPException(400, 'Invalid request origin')
            if unsafe:
                supplied = headers.get(b'origin')
                if supplied is not None:
                    # Chromium may send Origin:null for a no-referrer form POST.
                    # Only its browser-controlled same-origin Fetch Metadata permits this.
                    if supplied == b'null':
                        if headers.get(b'sec-fetch-site') != b'same-origin':
                            raise HTTPException(403, 'Cross-origin request rejected')
                    elif origin(supplied.decode('latin1')) != actual:
                        raise HTTPException(403, 'Cross-origin request rejected')
                # Same-site sibling subdomains must not be trusted as same-origin.
                if headers.get(b'sec-fetch-site') in {b'cross-site', b'same-site'}:
                    raise HTTPException(403, 'Cross-origin request rejected')
            if unsafe and path.rstrip('/') in {'/login', '/account/password'}:
                client = scope.get('client')
                await run_in_threadpool(scope['app'].state.login_limiter.check, client[0] if client else 'unknown')
                limit = 16384
                length = headers.get(b'content-length')
                if length is not None and (int(length) < 0 or int(length) > limit):
                    raise HTTPException(413, 'Authentication request is too large')
                body = bytearray()
                while True:
                    message = await receive()
                    if message['type'] == 'http.disconnect':
                        return
                    body.extend(message.get('body', b''))
                    if len(body) > limit:
                        raise HTTPException(413, 'Authentication request is too large')
                    if not message.get('more_body', False):
                        break
                sent = False
                upstream_receive = receive

                async def buffered_receive():
                    nonlocal sent
                    if not sent:
                        sent = True
                        return {'type': 'http.request', 'body': bytes(body), 'more_body': False}
                    return await upstream_receive()

                receive = buffered_receive
        except (ValueError, UnicodeError):
            response = JSONResponse({'detail': 'Invalid request origin or length'}, status_code=400)
        except HTTPException as exc:
            response = JSONResponse({'detail': exc.detail}, status_code=exc.status_code, headers=exc.headers)
        else:
            return await self.app(scope, receive, send)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        await response(scope, receive, send)
