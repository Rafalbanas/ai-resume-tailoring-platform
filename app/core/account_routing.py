"""Choose an account runtime only from a signed session and its server-side record."""
from starlette.concurrency import run_in_threadpool


class AccountRoutingMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        root = scope['app']
        accounts = getattr(root.state, 'accounts', None)
        if not accounts:
            return await self.app(scope, receive, send)
        session = scope['session']
        path = scope['path']
        if path.rstrip('/') == '/login':
            # A fresh sign-in replaces the browser's active account in every tab.
            if scope['method'] == 'GET':
                for candidate in accounts.values():
                    await run_in_threadpool(candidate.state.sessions.revoke, session.get('id', ''))
                session.clear()
            return await self.app(scope, receive, send)
        account = session.get('account', 'owner')
        candidate = accounts.get(account) if isinstance(account, str) else None
        if candidate is None:
            session.clear()
        elif candidate is not root:
            valid = await run_in_threadpool(
                candidate.state.sessions.valid, session.get('id', ''), candidate.state.auth_store.credential_version,
            )
            if valid:
                return await candidate(scope, receive, send)
            session.clear()
        return await self.app(scope, receive, send)
