import copy
import json
from types import SimpleNamespace

import httpx
import pytest
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.models.benchmark import BenchmarkRequest
from app.models.job import JobExtraction, JobRequirement, MatchLevel
from app.services.benchmark import run_benchmark
from app.services.offer_cleaning import clean_offer_text
from app.services.ollama_provider import OllamaProvider
from app.services.task_manager import TaskKind, TaskManager
from tests.test_queue_controls import login


def spec(**changes):
    return BenchmarkRequest(urls=['https://example.com/job'], confirm_costs=True, **changes)


def test_benchmark_validates_consent_limits_credentials_duplicates_and_unknown_fields():
    for invalid in [dict(urls=[]), dict(urls=['https://example.com'] * 2),
                    dict(urls=['https://user:secret@example.com/job']), dict(confirm_costs=False),
                    dict(context=100), dict(max_model_calls=49), dict(unrecognized=True)]:
        with pytest.raises(ValidationError):
            BenchmarkRequest.model_validate({'urls': ['https://example.com/job'], 'confirm_costs': True, **invalid})


def test_cleaner_keeps_qualifications_and_work_conditions_even_in_benefits():
    text = '''Nasze wymagania
znajomość Linux
To oferujemy
Free fruit and tea
English B2 required
Doświadczenie z SQL jest wymagane
100% remote
Twój zakres obowiązków
Administer servers
Mile widziane:
Knowledge of Azure
TECH STACK
Python
regular'''
    cleaned, metadata = clean_offer_text(text)
    assert 'Free fruit and tea' not in cleaned
    for value in ['znajomość Linux', 'English B2 required', 'Doświadczenie z SQL', '100% remote', 'Administer servers', 'Knowledge of Azure', 'TECH STACK', 'regular']:
        assert value in cleaned
    assert metadata['removed_lines'] == 1
    assert 'Free fruit and tea' in text


@pytest.mark.asyncio
@pytest.mark.parametrize('usage_known', [True, False])
async def test_paired_benchmark_reports_provider_usage_not_character_estimates(profile, usage_known):
    class Extractor:
        async def extract(self, url):
            return JobExtraction(company='Synthetic', role='Engineer', source=url,
                extraction_method='html', job_description='Requirements\nKnowledge of Python\nBenefits\nFree fruit')

    class Provider:
        model = 'synthetic'
        call_metrics = []

        async def for_model(self, model, context):
            selected = copy.copy(self)
            selected.call_metrics = []
            return selected

        async def _chat(self, model, prompt, payload, **kwargs):
            self.call_metrics.append({'stage': 'analyze_job', 'prompt_tokens': 101 if usage_known else None,
                                      'completion_tokens': 20 if usage_known else None, 'schema_bytes': 123})

        async def analyze_job(self, job, profile):
            await self._chat(None, 'Synthetic instructions', {'job_source': job.job_description, 'evidence': ['Synthetic evidence']})
            return SimpleNamespace(is_reliable=True, match_level=MatchLevel.MEDIUM,
                                   requirements=[JobRequirement(name='Python', source_quote='Knowledge of Python', priority='mandatory', status='missing')],
                                   completeness_issues=[], classification_issues=[], evidence_issues=[])

    state = SimpleNamespace(providers={'ollama': Provider()}, profile=profile, job_extractor=Extractor())
    snapshots = []
    report = await run_benchmark(spec(), state, lambda stage: None, lambda report: snapshots.append(copy.deepcopy(report)))
    full, cleaned = report['offers'][0]['variants']
    assert full['status'] == cleaned['status'] == 'ok'
    assert full['input_tokens'] == (101 if usage_known else None)
    assert full['output_tokens'] == (20 if usage_known else None)
    assert full['complete_usage'] is usage_known
    assert cleaned['input_composition_totals']['job_source']['bytes'] < full['input_composition_totals']['job_source']['bytes']
    assert report['attempted_model_calls'] == 2
    assert len(snapshots) >= 2
    budget_report = await run_benchmark(spec(max_model_calls=1), state, lambda stage: None)
    assert budget_report['attempted_model_calls'] == 1
    assert budget_report['offers'][0]['variants'][1]['status'] == 'failed'
    assert 'budget exhausted' in budget_report['offers'][0]['variants'][1]['error']


def test_api_is_authenticated_csrf_protected_idempotent_and_documented(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        assert client.get('/api/v1/benchmarks/' + 'a' * 32).status_code == 401
        login(client)
        # Production uses the configured task budget; this fixture's short budget
        # is raised only for admission tests, without making any provider calls.
        app.state.task_manager.budget_seconds = 900
        body = spec().model_dump(mode='json')
        headers = {'X-CSRF-Token': client.cookies.get('csrf_token'), 'Idempotency-Key': 'synthetic-benchmark-1'}
        assert client.post('/api/v1/benchmarks', json=body).status_code in {403, 422}
        created = client.post('/api/v1/benchmarks', json=body, headers=headers)
        assert created.status_code == 202, created.text
        repeated = client.post('/api/v1/benchmarks', json=body, headers=headers)
        assert repeated.json()['task_id'] == created.json()['task_id']
        assert app.state.task_manager.get_task(created.json()['task_id']).kind == TaskKind.BENCHMARK
        conflict = client.post('/api/v1/benchmarks', json={**body, 'context': 32768}, headers=headers)
        assert conflict.status_code == 409
        status = client.get(created.json()['status_url'])
        assert status.status_code == 200 and status.headers['cache-control'] == 'no-store'
        assert client.get('/api/v1/benchmarks/' + 'f' * 32).status_code == 404
        schema = client.get('/openapi.json').json()
        assert 'BenchmarkRequest' in schema['components']['schemas']
        assert 'BenchmarkJobResponse' in schema['components']['schemas']
        assert 'post' in schema['paths']['/api/v1/benchmarks']


@pytest.mark.asyncio
async def test_benchmark_uses_real_ollama_selection_and_structured_call_contract(profile):
    requests = []

    class Extractor:
        async def extract(self, url):
            return JobExtraction(company='Synthetic', role='Engineer', source=url,
                extraction_method='html', job_description='Requirements\nKnowledge of Python\nBenefits\nFree fruit')

    def handler(request):
        requests.append(request.url.path)
        if request.url.path == '/api/tags':
            return httpx.Response(200, json={'models': [{'name': 'synthetic:1b'}]})
        if request.url.path == '/api/show':
            return httpx.Response(200, json={'model_info': {'synthetic.context_length': 65536}})
        assert request.url.path == '/api/chat'
        payload = json.loads(json.loads(request.content)['messages'][1]['content'])
        rows = {passage['id']: {'k': 'requirement', 'n': 'Python', 's': 'missing', 'f': [],
                                'why': 'Not documented.', 'priority': 'mandatory'}
                if passage['text'] == 'Knowledge of Python' else {'k': 'context'}
                for passage in payload['passages']}
        return httpx.Response(200, json={'message': {'content': json.dumps({'assessments': rows})},
                                         'done': True, 'prompt_eval_count': 100, 'eval_count': 20})

    provider = OllamaProvider(Settings(_env_file=None, ollama_model='synthetic:1b'), transport=httpx.MockTransport(handler))
    state = SimpleNamespace(providers={'ollama': provider}, profile=profile, job_extractor=Extractor())
    report = await run_benchmark(spec(ollama_model='synthetic:1b'), state, lambda stage: None)
    assert requests[:2] == ['/api/tags', '/api/show']
    assert requests.count('/api/chat') == 2
    assert all(row['status'] == 'ok' for row in report['offers'][0]['variants'])
