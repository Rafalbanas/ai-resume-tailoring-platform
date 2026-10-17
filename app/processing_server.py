"""Private processing service: no account volumes, external model keys or public ingress."""
import asyncio
import json
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from starlette.concurrency import run_in_threadpool

from app.services.processing import local_process


@asynccontextmanager
async def lifespan(app):
    if os.environ.get('PROCESSING_CONTAINER_ISOLATED') == '1' and os.getpid() != 1:
        raise RuntimeError('The isolated processor must be container PID 1')
    if len(os.environ.get('PROCESSING_TOKEN', '')) < 32:
        raise RuntimeError('Configure an independent processing token of at least 32 characters')
    yield


app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
slots = asyncio.Semaphore(1)


@app.get('/health')
def health():
    return {'status': 'ok'}


@app.post('/process')
async def process(request: Request):
    token = os.environ.get('PROCESSING_TOKEN', '')
    supplied = request.headers.get('authorization', '')
    if not token or not secrets.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
        raise HTTPException(401, 'Authentication required')
    if slots.locked():
        raise HTTPException(429, 'Processing is busy')
    async with slots:
        body = bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body) > 16 * 1024 * 1024:
                raise HTTPException(413, 'Processing request is too large')
        try:
            value = json.loads(body)
            if value.get('operation') not in {'reference', 'photo', 'pdf', 'preview', 'metrics', 'docx', 'browser', 'check'}:
                raise HTTPException(400, 'Unsupported operation')
            limit = 20 if value['operation'] in {'reference', 'browser'} else 60
            timeout = max(0.1, min(limit, float(value.get('timeout_seconds', limit))))
            return await run_in_threadpool(local_process, value, timeout=timeout)
        except (ValueError, OSError) as exc:
            raise HTTPException(422, 'Document is invalid or exceeds processing limits') from exc
