"""Reuse server-owned analysis without paying for another interpretation stage."""
import pytest

from app.core.config import Settings
from app.main import app
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume
from app.services.ai_provider import ProviderUnavailableError
from app.services.gemini_provider import GeminiProvider
from app.services.ollama_provider import OllamaProvider
from app.services.resilient_provider import ResilientAIProvider
from tests.test_safe_resume_edits import saved_cv as saved_cv


def analysis_for(job):
    return JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                       missing_requirements=[], recommendation='REVIEW', match_level='LOW')


@pytest.mark.parametrize('name', ['ollama', 'gemini'])
async def test_retailoring_calls_only_cv_generation_and_keeps_level(profile, monkeypatch, name):
    provider = (OllamaProvider if name == 'ollama' else GeminiProvider)(Settings(_env_file=None))
    if name == 'gemini':
        provider.api_key = 'synthetic'
    async def forbidden(*args, **kwargs):
        raise AssertionError('Saved-analysis generation must not call analysis or the full pipeline')
    monkeypatch.setattr(provider, 'analyze_job', forbidden)
    monkeypatch.setattr(provider, 'tailor', forbidden)
    calls = []
    async def chat(model, prompt, payload, **kwargs):
        calls.append(payload)
        return TailoredResume(headline='Support', professional_summary='', core_skills=[], experience=[])
    monkeypatch.setattr(provider, '_chat', chat)
    router = ResilientAIProvider({name: provider}, default_primary=name, default_fallback='none')
    job = JobRequest(company='Example', role='Support', job_description='Python technical support and automation.')
    analysis = analysis_for(job)
    before = analysis.model_dump()
    for level in [0.2, 0.8]:
        job.tailoring_level = level
        result = await router.retailor(job, profile, analysis, requested_provider=name)
        assert result.analysis.model_dump() == before
        assert result.provider_used == name
        assert calls[-1]['tailoring_policy']['level'] == level
    assert len(calls) == 2  # One generation request per submitted setting; no analysis calls.
    assert analysis.model_dump() == before


async def test_retailoring_fallback_also_reuses_analysis(profile, monkeypatch):
    first = OllamaProvider(Settings(_env_file=None))
    second = GeminiProvider(Settings(_env_file=None))
    second.api_key = 'synthetic'
    calls = []
    async def failed(*args, **kwargs):
        calls.append('primary_generation')
        raise ProviderUnavailableError('synthetic unavailable')
    async def success(*args, **kwargs):
        calls.append('fallback_generation')
        return TailoredResume(headline='Support', professional_summary='', core_skills=[], experience=[])
    async def forbidden(*args, **kwargs):
        raise AssertionError('Fallback must not repeat analysis')
    monkeypatch.setattr(first, 'tailor_resume', failed)
    monkeypatch.setattr(second, 'tailor_resume', success)
    for provider in [first, second]:
        monkeypatch.setattr(provider, 'analyze_job', forbidden)
        monkeypatch.setattr(provider, 'tailor', forbidden)
    router = ResilientAIProvider({'ollama': first, 'gemini': second})
    job = JobRequest(company='Example', role='Support', job_description='Python technical support and automation.')
    result = await router.retailor(job, profile, analysis_for(job))
    assert calls == ['primary_generation', 'fallback_generation']
    assert result.fallback_used and result.provider_used == 'gemini'


def test_saved_analysis_retry_is_scoped_csrf_protected_and_preserves_cv(saved_cv):
    client, slug, folder, original, _ = saved_cv
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    endpoint = f'/retailor/application/{slug}'
    assert client.post(endpoint, data={'csrf_token': 'wrong', 'tailoring_level': '0.2'}).status_code == 403
    assert client.post(endpoint, data={'csrf_token': client.cookies.get('csrf_token'), 'tailoring_level': '1.1'}).status_code == 422
    response = client.post(endpoint, data={'csrf_token': client.cookies.get('csrf_token'),
        'tailoring_level': '0.2', 'job_description': 'Injected replacement offer'}, follow_redirects=False)
    assert response.status_code == 303
    task_id = response.headers['location'].split('/')[-2]
    task = app.state.task_manager.get_task(task_id)
    assert task.payload['job']['tailoring_level'] == 0.2
    assert 'Injected replacement offer' not in str(task.payload)
    assert task.payload['reuse_analysis']['company'] == 'Synthetic'
    assert {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()} == before
    assert app.state.storage.load_application(slug)[1] == original
    assert client.post('/retailor/application/missing', data={'csrf_token': client.cookies.get('csrf_token'),
        'tailoring_level': '0.5'}).status_code == 404


async def test_worker_revalidates_cached_analysis_before_any_generation(profile, tmp_path):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from app.services.ai_provider import AIProviderError
    from app.services.task_manager import TaskKind, TaskManager
    job = JobRequest(company='Example', role='Support', job_description='Requires Kubernetes in commercial production.')
    analysis = analysis_for(job)
    analysis.is_reliable = False
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {
        'job': job.model_dump(mode='json'), 'reuse_analysis': analysis.model_dump(mode='json'),
    }, 'synthetic-cached-analysis')
    provider = SimpleNamespace(retailor=AsyncMock())
    state = SimpleNamespace(profile=profile, skills_bank=None, provider=provider)
    with pytest.raises(AIProviderError, match='requires review'):
        await manager._execute_tailor(task, state)
    provider.retailor.assert_not_awaited()
