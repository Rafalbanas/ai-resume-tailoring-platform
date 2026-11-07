"""Deterministic retrieval contract, not a real embedding-quality benchmark."""
import pytest

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.services import hybrid_retrieval as hybrid
from app.services.fact_catalog import FactCatalog, FactEntry
from app.services.fact_retrieval import FactIndex, retrieve_facts


class FakeEmbeddings:
    def __init__(self):
        self.calls = []

    def embed_documents(self, texts):
        self.calls.append(list(texts))
        return [[1., 0.] if any(word in text.lower() for word in
                               ('ollama', 'language models', 'modeli językowych')) else [0., 1.]
                for text in texts]


@pytest.fixture(autouse=True)
def clear_cache():
    hybrid._cache.clear()
    hybrid._query_cache.clear()


def settings(**kwargs):
    return Settings(_env_file=None, hybrid_retrieval_enabled=True, embedding_model='fake', **kwargs)


def documents():
    return [FactEntry('project:one:fact:1', 'project',
                      'Built a FastAPI application integrating local Ollama inference through HTTP endpoints.',
                      0, 'Personal lab'),
            FactEntry('experience:two:fact:2', 'experience', 'Handled customer tickets.', 0, 'Support')]


@pytest.mark.parametrize('query', [
    'Experience integrating AI language models into backend applications',
    'Integracja modeli językowych z aplikacjami backendowymi',
])
def test_semantic_and_multilingual_candidates_keep_source_ids(query):
    docs = documents()
    fake = FakeEmbeddings()
    lexical = FactIndex(docs).search([(query, 1.)])
    ranked, trace = hybrid.hybrid_search(docs, [(query, 1.)], settings(), embeddings=fake)
    assert ranked[0][0] is docs[0]
    assert trace['method'] == 'local_bm25_dense_rrf'
    assert trace['candidates'][0]['dense_rank'] == 1
    assert trace['candidates'][0]['evidence_kind'] == 'project'
    if 'językowych' in query:
        assert lexical == []  # Reproduced lexical multilingual false negative.


def test_cache_is_bounded_and_invalidated_by_text_owner_model_and_endpoint():
    fake = FakeEmbeddings()
    cfg = settings()
    docs = documents()
    hybrid.hybrid_search(docs, [('language models', 1)], cfg, embeddings=fake)
    assert len(fake.calls) == 2
    _, trace = hybrid.hybrid_search(docs, [('language models', 1)], cfg, embeddings=fake)
    assert len(fake.calls) == 2 and trace['cache_hit']
    for i in range(6):
        changed = [FactEntry(docs[0].source_id, 'project', docs[0].text + str(i), 0, str(i))]
        hybrid.hybrid_search(changed, [('language models', 1)], cfg, embeddings=fake)
    assert len(hybrid._cache) == hybrid.MAX_CACHE_ENTRIES
    cfg.embedding_model_revision = 'changed'
    _, trace = hybrid.hybrid_search(docs, [('language models', 1)], cfg, embeddings=fake)
    assert not trace['cache_hit']


@pytest.mark.parametrize('bad', [RuntimeError('private secret'), [[float('nan')]], [[0., 0.]], [[1.]], []])
def test_unavailable_or_invalid_embeddings_fall_back_exactly(bad):
    class Broken:
        def embed_documents(self, texts):
            if isinstance(bad, Exception):
                raise bad
            return bad
    docs, queries = documents(), [('customer tickets', 1.)]
    ranked, trace = hybrid.hybrid_search(docs, queries, settings(), embeddings=Broken())
    assert ranked == FactIndex(docs).search(queries)
    assert trace['embedding_status'] == 'unavailable'
    assert 'private secret' not in str(trace)


def test_disabled_has_no_client_calls(monkeypatch):
    monkeypatch.setattr(hybrid, 'embedding_client', lambda _: pytest.fail('must not import optional client'))
    cfg = settings()
    cfg.hybrid_retrieval_enabled = False
    docs, queries = documents(), [('tickets', 1.)]
    assert hybrid.hybrid_search(docs, queries, cfg)[0] == FactIndex(docs).search(queries)


@pytest.mark.parametrize('endpoint', ['https://example.org', 'http://user:secret@localhost',
                                      'http://127.0.0.1/api', 'http://127.0.0.1?key=secret'])
def test_external_embedding_endpoints_rejected(endpoint):
    with pytest.raises(ValueError):
        hybrid.embedding_client(settings(embedding_base_url=endpoint))


def test_duplicate_ids_not_merged_by_similar_text():
    docs = documents()
    ranked, trace = hybrid.hybrid_search([*docs, docs[0]], [('language models', 1)],
                                        settings(), embeddings=FakeEmbeddings())
    assert len({e.source_id for e, _ in ranked}) == len(ranked)
    assert len(trace['candidates']) == len(ranked)


def test_generation_hybrid_integration_preserves_provenance_and_budget(monkeypatch):
    profile = CandidateProfile(personal={}, projects=[{
        'name': 'Personal lab', 'facts': [documents()[0].text]}])
    job = JobRequest(company='Example', role='Backend developer',
                     job_description='Requirements\nIntegracja modeli językowych z aplikacjami backendowymi')
    analysis = JobAnalysis(company='Example', role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation='REVIEW', match_level='LOW',
                           requirements=[JobRequirement(name='Integracja modeli językowych')])
    monkeypatch.setattr(hybrid, 'embedding_client', lambda _: FakeEmbeddings())
    result = retrieve_facts(job, profile, analysis, settings=settings())
    assert result.trace['method'] == 'local_bm25_dense_rrf'
    assert all(e == FactCatalog(profile).get(e.source_id) for e in result.entries)
    assert all(r['reason'] == 'hybrid_match' for r in result.trace['selected'])
    assert not retrieve_facts(job, profile, analysis, settings=settings(), max_chars=1).entries


@pytest.mark.asyncio
async def test_analysis_hints_retain_all_evidence_and_do_not_set_status(monkeypatch):
    from app.services.ollama_analysis import AnalysisInventory
    profile = CandidateProfile(personal={}, projects=[{'name': 'Personal lab', 'facts': [documents()[0].text]}])
    job = JobRequest(company='Example', role='Developer',
                     job_description='Requirements\nExperience integrating language models')
    inventory = AnalysisInventory.build(job, profile)
    before = dict(inventory.evidence)
    fake = FakeEmbeddings()
    monkeypatch.setattr(hybrid, 'embedding_client', lambda _: fake)
    await hybrid.prepare_inventory_retrieval(inventory, settings())
    assert inventory.evidence == before
    assert inventory.retrieval_hints
    assert len(fake.calls) == 2
    assert set(inventory.payload(list(inventory.passages))['evidence']) == set(before)


def test_actual_langchain_adapter_is_lazy_local_and_bounded():
    pytest.importorskip('langchain_ollama')
    client = hybrid.embedding_client(settings())
    assert client.model == 'fake' and client.keep_alive == 0
    assert client.client_kwargs['timeout'] == 10


def test_missing_optional_dependency_keeps_lexical_path(monkeypatch):
    import builtins
    original = builtins.__import__
    def without_langchain(name, *args, **kwargs):
        if name == 'langchain_ollama':
            raise ImportError('optional dependency not installed')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', without_langchain)
    docs, queries = documents(), [('customer tickets', 1.)]
    ranked, trace = hybrid.hybrid_search(docs, queries, settings())
    assert ranked == FactIndex(docs).search(queries)
    assert trace['embedding_status'] == 'unavailable'


def test_optional_real_local_embedding():
    import os
    model = os.environ.get('CVTAILOR_TEST_EMBEDDING_MODEL')
    if not model:
        pytest.skip('Explicit already-installed local embedding model required')
    pytest.importorskip('langchain_ollama')
    cfg = settings()
    cfg.embedding_model = model
    _, trace = hybrid.hybrid_search(documents(), [('language models', 1)], cfg)
    assert trace['embedding_status'] == 'ready'  # Do not hide integration failures.


@pytest.mark.asyncio
@pytest.mark.parametrize('worker_failure', [False, True])
async def test_cancelled_retrieval_waits_for_owning_thread(worker_failure):
    import asyncio
    import threading
    loop = asyncio.get_running_loop()
    started, release, finished = asyncio.Event(), threading.Event(), threading.Event()
    def work():
        loop.call_soon_threadsafe(started.set)
        release.wait(timeout=5)
        finished.set()
        if worker_failure:
            raise RuntimeError('worker error after cancellation')
    task = asyncio.create_task(hybrid.retrieval_in_thread(work))
    await asyncio.wait_for(started.wait(), timeout=5)
    task.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert finished.is_set()
