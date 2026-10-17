"""Bound request bodies before any form/JSON parser, including chunked transfers."""
from fastapi import HTTPException
from starlette.responses import JSONResponse


class RequestSizeMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        upload = path.endswith('/photo') or path.endswith('/references/upload')
        limit = 12 * 1024 * 1024 if upload else 512 * 1024
        headers = dict(scope['headers'])
        try:
            length = int(headers.get(b'content-length', b'0'))
            if length < 0 or length > limit:
                raise ValueError
        except ValueError:
            return await JSONResponse({'detail': 'Request body exceeds the size limit'}, status_code=413)(scope, receive, send)
        size = 0
        async def bounded_receive():
            nonlocal size
            message = await receive()
            size += len(message.get('body', b''))
            if size > limit:
                raise HTTPException(413, 'Request body exceeds the size limit')
            return message
        return await self.app(scope, bounded_receive, send)
