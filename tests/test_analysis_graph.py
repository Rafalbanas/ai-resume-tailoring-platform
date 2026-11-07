from types import SimpleNamespace

import pytest

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.services.ai_provider import ProviderResponseError
from app.services.analysis_graph import analyze_with_graph
from app.services.ollama_analysis import CompactAssessment, CompactInterpretation

pytest.importorskip('langgraph')


def test_graph_unavailable_detection(monkeypatch):
    import builtins

    from app.services.analysis_graph import graph_available
    original = builtins.__import__
    def without_langgraph(name, *args, **kwargs):
        if name == 'langgraph.graph':
            raise ImportError('optional dependency not installed')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_langgraph)
    assert not graph_available()


@pytest.mark.asyncio
@pytest.mark.parametrize('mode', ['success', 'recover', 'always_fail', 'invalid_citation', 'coverage'])
async def test_real_graph_bounded_recovery_and_termination(mode):
    calls = []
    async def chat(model, prompt, payload, **kwargs):
        calls.append(prompt)
        if mode == 'always_fail' or mode == 'recover' and len(calls) == 1:
            raise ProviderResponseError('bad JSON')
        rows = []
        for p in payload['passages']:
            if p['text'].startswith('Experience'):
                if mode == 'coverage':
                    continue
                rows.append(CompactAssessment(
                    p=p['id'], k='requirement', n='PhotonStack', priority='mandatory',
                    why='Not confirmed in the profile.', s='strong' if mode == 'invalid_citation' else 'missing',
                    f=['F999'] if mode == 'invalid_citation' else []))
            else:
                rows.append(CompactAssessment(p=p['id'], k='context'))
        return CompactInterpretation(rows=rows)
    provider = SimpleNamespace(skills_bank=None, semantic_settings=Settings(_env_file=None), _chat=chat)
    job = JobRequest(company='Example', role='Engineer', job_description='Requirements\nExperience with PhotonStack.')
    profile = CandidateProfile(personal={})
    if mode in {'always_fail', 'coverage', 'invalid_citation'}:
        with pytest.raises(ProviderResponseError, match='bounded retry'):
            await analyze_with_graph(provider, job, profile)
        assert len(calls) == 2
    else:
        result = await analyze_with_graph(provider, job, profile)
        assert result.requirements[0].status == 'missing'
        assert len(calls) == (2 if mode == 'recover' else 1)
        assert result.job_source['sha256']
    if len(calls) == 2:
        assert 'VALIDATION FEEDBACK' in calls[-1]


@pytest.mark.asyncio
async def test_persistent_validation_issues_never_become_success(monkeypatch):
    from app.services.analysis_validator import AnalysisValidator
    original = AnalysisValidator.validate
    calls = []
    def incomplete(self, *args, **kwargs):
        result = original(self, *args, **kwargs)
        result.is_reliable = False
        result.completeness_issues.append('Incomplete source coverage')
        return result
    monkeypatch.setattr(AnalysisValidator, 'validate', incomplete)
    async def chat(model, prompt, payload, **kwargs):
        calls.append(prompt)
        return CompactInterpretation(rows=[
            CompactAssessment(p=p['id'], k='requirement', n='PhotonStack', why='Not confirmed.', priority='mandatory')
            if p['text'].startswith('Experience') else CompactAssessment(p=p['id'], k='context')
            for p in payload['passages']])
    provider = SimpleNamespace(skills_bank=None, semantic_settings=Settings(_env_file=None), _chat=chat)
    result = await analyze_with_graph(provider, JobRequest(
        company='Example', role='Engineer', job_description='Requirements\nExperience with PhotonStack.'),
        CandidateProfile(personal={}))
    assert len(calls) == 2 and not result.is_reliable
    assert 'Incomplete source coverage' in calls[1]


@pytest.mark.asyncio
@pytest.mark.parametrize('provider_name', ['ollama', 'gemini'])
@pytest.mark.parametrize('available', [True, False])
async def test_provider_graph_flag_and_missing_dependency_fallback(monkeypatch, provider_name, available):
    from app.services import analysis_graph
    from app.services.gemini_provider import GeminiProvider
    from app.services.ollama_provider import OllamaProvider
    cfg = Settings(_env_file=None, analysis_graph_enabled=True)
    provider = (OllamaProvider if provider_name == 'ollama' else GeminiProvider)(cfg)
    calls = []
    async def chat(model, prompt, payload, **kwargs):
        calls.append(prompt)
        return CompactInterpretation(rows=[
            CompactAssessment(p=p['id'], k='requirement', n='PhotonStack', why='Not confirmed.', priority='mandatory')
            if p['text'].startswith('Experience') else CompactAssessment(p=p['id'], k='context')
            for p in payload['passages']])
    monkeypatch.setattr(provider, '_chat', chat)
    monkeypatch.setattr(analysis_graph, 'graph_available', lambda: available)
    result = await provider.analyze_job(JobRequest(
        company='Example', role='Engineer', job_description='Requirements\nExperience with PhotonStack.'),
        CandidateProfile(personal={}))
    assert result.requirements[0].status == 'missing'
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_graph_uses_semantic_candidate_hints_but_validates_literal_sources(monkeypatch):
    from app.services import hybrid_retrieval
    class FakeEmbeddings:
        def embed_documents(self, texts):
            return [[1., 0.] for _ in texts]
    hybrid_retrieval._cache.clear()
    hybrid_retrieval._query_cache.clear()
    monkeypatch.setattr(hybrid_retrieval, 'embedding_client', lambda _: FakeEmbeddings())
    fact = 'Built a FastAPI application integrating local Ollama inference through HTTP endpoints.'
    profile = CandidateProfile(personal={}, projects=[{'name': 'Personal lab', 'facts': [fact]}])
    quote = 'Experience integrating AI language models into backend applications'
    async def chat(model, prompt, payload, **kwargs):
        assert 'retrieval_hints' in payload
        rows = []
        for p in payload['passages']:
            if p['text'] == quote:
                hints = payload['retrieval_hints'][p['id']]
                supporting = [fid for fid in hints if payload['evidence'][fid][2] == fact]
                assert supporting
                rows.append(CompactAssessment(p=p['id'], k='requirement', n=quote,
                                              priority='mandatory', s='strong', f=supporting,
                                              why='Implemented local inference integration in a personal project.'))
            else:
                rows.append(CompactAssessment(p=p['id'], k='context'))
        return CompactInterpretation(rows=rows)
    provider = SimpleNamespace(skills_bank=None, _chat=chat, semantic_settings=Settings(
        _env_file=None, hybrid_retrieval_enabled=True, embedding_model='graph-fake'))
    result = await analyze_with_graph(provider, JobRequest(
        company='Example', role='Developer', job_description='Requirements\n' + quote), profile)
    req = result.requirements[0]
    assert req.status == 'strong'
    assert req.source_quote == quote
    assert req.evidence == [fact]
    assert all(source['type'] == 'project' for source in req.evidence_sources)


@pytest.mark.asyncio
async def test_graph_preserves_coverage_when_existing_planner_splits_batches():
    calls = []
    quotes = [f'Experience with PhotonTool{index}.' for index in range(12)]
    async def chat(model, prompt, payload, **kwargs):
        calls.append([p['text'] for p in payload['passages']])
        return CompactInterpretation(rows=[
            CompactAssessment(p=p['id'], k='requirement', n=p['text'], why='Not confirmed.', priority='mandatory')
            if p['text'] in quotes else CompactAssessment(p=p['id'], k='context')
            for p in payload['passages']])
    provider = SimpleNamespace(skills_bank=None, _chat=chat, analysis_output=512,
                               semantic_settings=Settings(_env_file=None))
    result = await analyze_with_graph(provider, JobRequest(
        company='Example', role='Developer', job_description='Requirements\n' + '\n'.join(quotes)),
        CandidateProfile(personal={}))
    assert len(calls) > 1
    assert sorted(r.source_quote for r in result.requirements) == sorted(quotes)
    assert all(r.status == 'missing' for r in result.requirements)
    assert result.is_reliable
