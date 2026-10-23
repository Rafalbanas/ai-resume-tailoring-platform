"""HTTP diagnosis remains useful without persisting prompts or upstream error text."""
import hashlib
import json
from types import SimpleNamespace

import httpx
import pytest
from jinja2 import Environment, FileSystemLoader
from pydantic import BaseModel

from app.core.config import Settings
from app.services.ai_provider import AIProviderError
from app.services.diagnostics import DiagnosticLogStore
from app.services.ollama_analysis import OllamaAnalysisError
from app.services.ollama_provider import OllamaProvider
from app.services.resilient_provider import ResilientAIProvider
from app.services.storage import Storage
from app.services.task_manager import TaskKind, TaskManager
from tests.test_provider_fallback import FailingProvider, SucceedingProvider, job


class Reply(BaseModel):
    answer: str


@pytest.mark.parametrize('status,message,code', [
    (400, 'input length exceeds context length', 'context_budget'),
    (400, 'prompt too long', 'context_budget'),
    (500, 'unable to allocate memory', 'memory_exhausted'),
    (500, 'model requires more system memory', 'memory_exhausted'),
    (404, "model 'synthetic' not found", 'model_not_found'),
    (400, 'invalid JSON schema', 'invalid_schema'),
    (401, 'denied', 'authentication'),
    (403, 'denied', 'authentication'),
    (429, 'too many requests', 'rate_limited'),
    (404, 'not found', 'endpoint_not_found'),
    (422, 'unknown parameter', 'invalid_request'),
    (500, 'runner crashed', 'server_error'),
    (502, 'request context could not be initialized', 'server_error'),
])
async def test_http_failure_records_specific_safe_reason(tmp_path, caplog, status, message, code):
    private = 'PRIVATE-CV-SECRET-123456 <script>private()</script>'
    content = json.dumps({'error': message + ' ' + private}).encode()
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(status, content=content)
    provider = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    with pytest.raises(OllamaAnalysisError) as raised:
        await provider._chat(Reply, 'Private prompt ' + private, {'stage': 'analyze_job', 'candidate': private})
    metric = provider.call_metrics[-1]
    assert metric['http_status'] == status and metric['error_code'] == code
    assert metric['error_kind'] == ('context_budget' if code == 'context_budget' else 'http')
    assert metric['client_ms'] >= 0 and metric['started_at']
    assert metric['request_bytes'] == len(requests[0].content)
    assert metric['schema_bytes'] > 0 and metric['prompt_chars'] > 0
    assert requests[0].headers['X-Request-ID'] == metric['call_id']
    assert metric['response_sha256'] == hashlib.sha256(content).hexdigest()
    assert f'HTTP {status}' in str(raised.value) and code in str(raised.value)
    assert metric['call_id'] in str(raised.value) and metric['call_id'] in caplog.text
    store = DiagnosticLogStore(tmp_path)
    store.record(company='Synthetic', role='Synthetic', requested_provider='ollama', provider_used='ollama',
                 model_used='synthetic', fallback_occurred=False, call_metrics=provider.call_metrics)
    saved = store.list_runs()[0]['call_metrics'][0]
    assert saved['error_summary'] and saved['error_code'] == code
    assert saved['http_status'] == status and saved['response_bytes'] == len(content)
    assert private not in store.file_path.read_text() + str(raised.value) + caplog.text + json.dumps(provider.call_metrics)


@pytest.mark.parametrize('kind', ['timeout', 'connection', 'envelope'])
async def test_non_http_failures_keep_timing_and_correlation(kind):
    def handler(request):
        if kind == 'timeout':
            raise httpx.ReadTimeout('PRIVATE error', request=request)
        if kind == 'connection':
            raise httpx.ConnectError('PRIVATE error', request=request)
        return httpx.Response(200, text='invalid json PRIVATE')
    provider = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    with pytest.raises(OllamaAnalysisError):
        await provider._chat(Reply, 'Synthetic', {'stage': 'analyze_job'})
    metric = provider.call_metrics[-1]
    assert metric['call_id'] and metric['client_ms'] >= 0
    assert metric['http_status'] == (200 if kind == 'envelope' else None)
    assert 'PRIVATE' not in json.dumps(metric)


async def test_primary_http_error_survives_fallback_and_task_persistence(tmp_path, profile):
    primary = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(
        lambda _: httpx.Response(500, json={'error': 'unable to allocate memory PRIVATE'})))
    router = ResilientAIProvider({'ollama': primary, 'gemini': SucceedingProvider('gemini')})
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json'), 'llm_provider': 'ollama'}, 'synthetic')
    store = DiagnosticLogStore(tmp_path)
    state = SimpleNamespace(provider=router, storage=Storage(tmp_path), diagnostics=store, profile=profile, skills_bank=None)
    await manager._execute_tailor(task, state)
    saved = store.list_runs()[0]
    assert saved['task_id'] == task.task_id and saved['fallback_occurred']
    assert saved['call_metrics'][0]['http_status'] == 500
    assert saved['call_metrics'][0]['error_code'] == 'memory_exhausted'
    assert 'PRIVATE' not in store.file_path.read_text()
    ready = manager.get_task(task.task_id)
    _, response = state.storage.load_draft(ready.result['draft_id'])
    assert response.call_metrics[0]['call_id'] == saved['call_metrics'][0]['call_id']
    assert 'HTTP 500' in response.fallback_reason


async def test_dual_failure_keeps_primary_and_fallback_metrics(profile):
    primary = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(
        lambda _: httpx.Response(400, json={'error': 'prompt too long'})))
    failure = AIProviderError('Synthetic Gemini error')
    failure.call_metrics = [{'provider': 'gemini', 'http_status': 503}]
    router = ResilientAIProvider({'ollama': primary, 'gemini': FailingProvider('gemini', failure)})
    with pytest.raises(AIProviderError) as raised:
        await router.tailor(job(), profile)
    assert [c['http_status'] for c in raised.value.call_metrics] == [400, 503]


def test_diagnostics_render_new_and_legacy_metrics_without_raw_body(tmp_path):
    store = DiagnosticLogStore(tmp_path)
    store.record(company='Synthetic', role='Synthetic', requested_provider='ollama', provider_used='gemini',
                 model_used='synthetic', fallback_occurred=True, task_id='a' * 32,
                 call_metrics=[{'http_status': 500, 'call_id': 'b' * 32, 'error_code': 'memory_exhausted',
                                'error_summary': '<script>PRIVATE</script>', 'raw_response': 'PRIVATE'},
                               {'provider': 'gemini', 'stage': 'analyze_job'}])
    saved = store.list_runs()[0]
    assert 'PRIVATE' not in store.file_path.read_text()
    template = Environment(loader=FileSystemLoader('templates')).get_template('diagnostics.html')
    html = template.render(runs=[saved], health={'providers': {}}, app_root_path='/workspace',
                           request=SimpleNamespace(state=SimpleNamespace(authenticated=False)))
    assert 'HTTP 500' in html and 'could not allocate enough memory' in html
    assert 'b' * 32 in html and '/workspace/tasks/' + 'a' * 32 + '/view' in html
    assert 'PRIVATE' not in html


@pytest.mark.parametrize('fallback_metrics', [False, True])
async def test_failed_task_diagnostics_keep_both_attempts(tmp_path, profile, fallback_metrics):
    primary = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(
        lambda _: httpx.Response(400, json={'error': 'prompt too long PRIVATE'})))
    failure = AIProviderError('Synthetic fallback unavailable')
    if fallback_metrics:
        failure.call_metrics = [{'provider': 'gemini', 'http_status': 503}]
    router = ResilientAIProvider({'ollama': primary, 'gemini': FailingProvider('gemini', failure)})
    manager, store = TaskManager(tmp_path), DiagnosticLogStore(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    state = SimpleNamespace(provider=router, diagnostics=store, profile=profile, skills_bank=None)
    with pytest.raises(AIProviderError):
        await manager._execute_tailor(task, state)
    saved = store.list_runs()[0]
    assert saved['task_id'] == task.task_id and saved['status'] == 'error'
    assert saved['fallback_occurred']
    assert [c['http_status'] for c in saved['call_metrics']] == ([400, 503] if fallback_metrics else [400])
    assert 'PRIVATE' not in store.file_path.read_text()
