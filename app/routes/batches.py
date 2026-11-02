"""Authenticated batch submission using the same session/CSRF boundary as the UI."""
import json
from typing import Annotated

from fastapi import APIRouter, File, Form, Header, HTTPException, Request, Security, UploadFile
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie
from pydantic import ValidationError

from app.models.batch import BatchRequest, parse_url_file
from app.models.batch_api import BatchOptionsResponse, BatchResponse
from app.routes.web import guard, ollama_model_options, queue_control_guard
from app.services.task_manager import TaskKind, TaskStatus, compute_idempotency_key

session_auth = APIKeyCookie(name='session', scheme_name='SessionCookie', auto_error=False)
router = APIRouter(prefix='/api/v1/batches', tags=['Batch CV generation'],
                   dependencies=[Security(session_auth)],
                   responses={401: {'description': 'Authenticated session required'},
                              403: {'description': 'CSRF validation failed or demo account denied'},
                              409: {'description': 'Idempotency key conflicts with an existing payload'},
                              413: {'description': 'Request body exceeds the limit'},
                              429: {'description': 'Rate, queue or storage limit reached'}})
ClientKey = Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=128,
                                pattern=r'^[A-Za-z0-9._:-]+$')]
CSRF = Annotated[str, Header(alias='X-CSRF-Token')]


def response_for(request, task, status_code=200):
    root = request.scope.get('root_path', '')
    url = f'{root}/api/v1/batches/{task.task_id}'
    result = task.result
    if result:
        result = {**result, 'history_url': f'{root}/history', 'redirect_url': f'{root}/history',
                  'items': [{key: (root + value if key.endswith('_url') and isinstance(value, str)
                                  and value.startswith('/') else value)
                             for key, value in item.items()} for item in result.get('items', [])]}
    headers = {'Cache-Control': 'no-store'}
    if status_code == 202:
        headers.update({'Location': url, 'Retry-After': '3'})
    return JSONResponse({'task_id': task.task_id, 'status': task.status.value,
                         'status_url': url, 'view_url': f'{root}/tasks/{task.task_id}/view',
                         'stage': task.stage, 'result': result, 'error': task.error},
                        status_code=status_code,
                        headers=headers)


def submit(request, spec, csrf_token, client_key):
    queue_control_guard(request, csrf_token)
    if request.app.state.settings.demo_mode:
        raise HTTPException(403, 'Batch generation is disabled for the demo account')
    if spec.llm_provider != 'auto' and spec.llm_provider not in request.app.state.providers:
        raise HTTPException(422, 'Selected provider is not configured')
    manager = request.app.state.task_manager
    payload = {'batch': spec.model_dump(mode='json')}
    key = compute_idempotency_key('batch', client_key=client_key)
    task = manager.get_or_create_idempotent(TaskKind.BATCH, payload, key)
    return response_for(request, task, 202 if task.status in {TaskStatus.QUEUED, TaskStatus.RUNNING} else 200)


@router.get('/options', response_model=BatchOptionsResponse, summary='List providers, installed Ollama models and CV themes')
async def batch_options(request: Request):
    guard(request)
    options = await ollama_model_options(request)
    return JSONResponse({'providers': ['auto', *request.app.state.providers], **options,
                         'gemini_model': request.app.state.settings.gemini_model,
                         'templates': ['ats_classic', 'modern_sidebar'], 'max_urls': 20,
                         'max_file_bytes': 65536}, headers={'Cache-Control': 'no-store'})


@router.post('', status_code=202, response_model=BatchResponse,
             responses={200: {'model': BatchResponse, 'description': 'Existing finished batch'}},
             summary='Queue explicitly selected offers for analysis and optional PDF/DOCX generation')
async def create_batch(request: Request, spec: BatchRequest, csrf_token: CSRF, idempotency_key: ClientKey):
    return submit(request, spec, csrf_token, idempotency_key)


@router.post('/upload', status_code=202, response_model=BatchResponse,
             responses={200: {'model': BatchResponse, 'description': 'Existing finished batch'}},
             summary='Upload a UTF-8 whitespace-separated URL list with JSON options')
async def upload_batch(request: Request, file: Annotated[UploadFile, File()],
                       csrf_token: CSRF, idempotency_key: ClientKey,
                       options: Annotated[str, Form(max_length=4096)] = '{}'):
    try:
        content = await file.read(65537)
        values = json.loads(options)
        if not isinstance(values, dict) or 'urls' in values:
            raise ValueError('Options must be an object without urls')
        spec = BatchRequest(urls=parse_url_file(content), **values)
    except (ValueError, ValidationError) as exc:
        raise HTTPException(422, 'Invalid UTF-8 URL list or batch options (maximum 20 URLs / 64 KiB)') from exc
    finally:
        await file.close()
    return submit(request, spec, csrf_token, idempotency_key)


@router.get('/{task_id}', response_model=BatchResponse, responses={404: {'description': 'Batch not found'}},
            summary='Read batch state and per-offer incremental results')
async def get_batch(request: Request, task_id: str):
    guard(request)
    task = request.app.state.task_manager.get_task(task_id)
    if task is None or task.kind != TaskKind.BATCH:
        raise HTTPException(404, 'Batch not found')
    return response_for(request, task)
