"""Stage-one versioned benchmark API: session + CSRF, bounded and idempotent."""
import json
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import APIKeyCookie

from app.models.benchmark import BenchmarkJobResponse, BenchmarkRequest
from app.routes.web import guard, queue_control_guard
from app.services.task_manager import TaskKind, TaskStatus, compute_idempotency_key

router = APIRouter(prefix='/api/v1/benchmarks', tags=['Benchmarks'])
session_auth = APIKeyCookie(name='session', scheme_name='SessionCookie', auto_error=False,
                           description='Authenticated browser session. Stage-two integration tokens are not implemented by this endpoint.')


def response_for(request, task, status_code=200):
    root = request.scope.get('root_path', '')
    headers = {'Cache-Control': 'no-store'}
    if status_code == 202:
        headers.update(Location=f'{root}/api/v1/benchmarks/{task.task_id}', **{'Retry-After': '3'})
    return JSONResponse({'task_id': task.task_id, 'status': task.status.value, 'stage': task.stage,
                         'status_url': f'{root}/api/v1/benchmarks/{task.task_id}',
                         'view_url': f'{root}/tasks/{task.task_id}/view',
                         'report': (task.result or {}).get('report'), 'error': task.error},
                        status_code=status_code, headers=headers)


@router.post('', status_code=202, response_model=BenchmarkJobResponse,
             dependencies=[Security(session_auth)],
             responses={200: {'model': BenchmarkJobResponse, 'description': 'Previously completed idempotent request'},
                        409: {'description': 'Idempotency conflict or missing Ollama provider'}},
             summary='Queue a paired full/cleaned Ollama analysis benchmark')
async def create_benchmark(request: Request, spec: BenchmarkRequest,
                           csrf_token: Annotated[str, Header(alias='X-CSRF-Token')],
                           idempotency_key: Annotated[str, Header(alias='Idempotency-Key', min_length=8, max_length=128, pattern=r'^[A-Za-z0-9._:-]+$')]):
    queue_control_guard(request, csrf_token)
    if request.app.state.settings.demo_mode:
        raise HTTPException(403, 'Paid/resource-intensive benchmarks are disabled for the demo account')
    manager = request.app.state.task_manager
    if len(spec.urls) * 2 * spec.case_timeout_seconds + 60 > manager.budget_seconds:
        raise HTTPException(422, 'Paired case deadlines exceed the task budget. Reduce URLs or case_timeout_seconds.')
    if 'ollama' not in request.app.state.providers:
        raise HTTPException(409, 'Ollama is not configured')
    payload = {'benchmark': spec.model_dump(mode='json')}
    key = compute_idempotency_key('benchmark', client_key=idempotency_key)
    # No await between lookup and admission: same-process submissions are atomic.
    existing = manager.find_by_idempotency_key(key)
    if existing:
        if json.dumps(existing.payload, sort_keys=True) != json.dumps(payload, sort_keys=True):
            raise HTTPException(409, 'Idempotency-Key already belongs to a different benchmark request')
        return response_for(request, existing, 202 if existing.status in {TaskStatus.QUEUED, TaskStatus.RUNNING} else 200)
    task = manager.create_task(TaskKind.BENCHMARK, payload, key)
    manager.retain_history(task)
    return response_for(request, task, 202)


@router.get('/{task_id}', response_model=BenchmarkJobResponse, dependencies=[Security(session_auth)],
            summary='Read benchmark state and its incremental or final report')
async def get_benchmark(request: Request, task_id: str):
    guard(request)
    task = request.app.state.task_manager.get_task(task_id)
    if task is None or task.kind != TaskKind.BENCHMARK:
        raise HTTPException(404, 'Benchmark not found')
    return response_for(request, task)
