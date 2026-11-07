"""Local retrieval only: neither vectors nor ranks establish qualifications.

Lazy LangChain integration, bounded process-local vector-only LRU, no disk writes.
Cache identity includes the complete corpus, endpoint and explicit model revision.
"""
import hashlib
import json
import math
import threading
from collections import OrderedDict

from pydantic import BaseModel, Field

from app.services.fact_retrieval import FactIndex

_lock = threading.Lock()
_cache = OrderedDict()
_query_cache = OrderedDict()
MAX_CACHE_ENTRIES = 4
MAX_DOCUMENTS = 512
MAX_SOURCE_CHARS = 128_000
MAX_CACHED_SCALARS = 1_000_000


class RankedEvidence(BaseModel):
    source_id: str
    score: float = Field(ge=0)
    lexical_rank: int | None = None
    dense_rank: int | None = None
    cosine: float | None = None
    evidence_kind: str


def embedding_client(settings):
    # Candidate text must never be sent to an external embedding endpoint.
    from urllib.parse import urlsplit
    endpoint = urlsplit(settings.embedding_base_url)
    if (endpoint.scheme not in {'http', 'https'} or endpoint.hostname not in
            {'localhost', '127.0.0.1', '::1'} or endpoint.username or endpoint.password
            or endpoint.query or endpoint.fragment or endpoint.path not in {'', '/'}):
        raise ValueError('Embeddings require an explicit loopback endpoint')
    from langchain_ollama import OllamaEmbeddings
    return OllamaEmbeddings(
        model=settings.embedding_model, base_url=settings.embedding_base_url,
        keep_alive=0, client_kwargs={'timeout': settings.embedding_timeout_seconds,
                                    'trust_env': False, 'follow_redirects': False},
    )


def _unit(vector):
    if not vector or len(vector) > 2048 or any(not math.isfinite(v) for v in vector):
        raise ValueError('Invalid embedding')
    norm = math.sqrt(sum(v * v for v in vector))
    if not norm or not math.isfinite(norm):
        raise ValueError('Empty embedding')
    return tuple(v / norm for v in vector)


def hybrid_search(documents, queries, settings, *, embeddings=None):
    """Weighted per-query RRF, cosine dense ranking and explicit scope tie-break.

    Return the exact lexical result on *any* optional embedding failure. Facts are
    deduplicated by canonical ID, never by similar text or project title.
    """
    documents = list({e.source_id: e for e in documents}.values())
    index = FactIndex(documents)
    lexical = index.search(queries)
    diagnostic = {'method': 'local_bm25', 'embedding_status': 'disabled', 'candidates': []}
    if not settings.hybrid_retrieval_enabled:
        return lexical, diagnostic
    diagnostic['embedding_status'] = 'unavailable'
    if (not settings.embedding_model or not documents or len(documents) > MAX_DOCUMENTS
            or sum(len(e.text) for e in documents) > MAX_SOURCE_CHARS
            or len(queries) > 128 or sum(len(q) for q, _ in queries) > 64_000):
        return lexical, diagnostic
    try:
        # Context preserves source category/owner without adding inferred claims.
        texts = [f'{e.kind} | {e.owner_name} | {e.text}' for e in documents]
        key = hashlib.sha256(json.dumps([
            'hybrid-v1', settings.embedding_base_url, settings.embedding_model,
            settings.embedding_model_revision,
            [(e.source_id, text) for e, text in zip(documents, texts, strict=True)],
        ], ensure_ascii=False).encode()).hexdigest()
        # Serialize embedding work and cache fills. Never cache raw candidate text.
        with _lock:
            client = embeddings
            cached = key in _cache
            vectors = _cache.get(key)
            if vectors is None:
                client = client or embedding_client(settings)
                vectors = tuple(_unit(v) for v in client.embed_documents(texts))
                if len(vectors) != len(documents) or len({len(v) for v in vectors}) != 1:
                    raise ValueError('Embedding corpus shape mismatch')
                if sum(map(len, vectors)) > MAX_CACHED_SCALARS:
                    raise ValueError('Embedding corpus exceeds memory budget')
                _cache[key] = vectors
                while (len(_cache) > MAX_CACHE_ENTRIES
                       or sum(sum(map(len, value)) for value in _cache.values()) > MAX_CACHED_SCALARS):
                    _cache.popitem(last=False)
            _cache.move_to_end(key)
            # One batched call for all requirements; no simultaneous Ollama calls.
            query_keys = [hashlib.sha256((key + q).encode()).hexdigest() for q, _ in queries]
            missing = list(dict.fromkeys(k for k in query_keys if k not in _query_cache))
            query_text = dict(zip(query_keys, [q for q, _ in queries], strict=True))
            if missing:
                client = client or embedding_client(settings)
                generated = [_unit(v) for v in client.embed_documents([query_text[k] for k in missing])]
                if len(generated) != len(missing):
                    raise ValueError('Embedding query count mismatch')
                for k, v in zip(missing, generated, strict=True):
                    if len(v) != len(vectors[0]):
                        raise ValueError('Embedding dimension mismatch')
                    _query_cache[k] = v
            query_vectors = [_query_cache[k] for k in query_keys]
            for k in query_keys:
                _query_cache.move_to_end(k)
            while len(_query_cache) > 128:
                _query_cache.popitem(last=False)
        if len(query_vectors) != len(queries):
            raise ValueError('Embedding query count mismatch')
        scores, details = {}, {}
        for (query, weight), vector in zip(queries, query_vectors, strict=True):
            if len(vector) != len(vectors[0]):
                raise ValueError('Embedding dimension mismatch')
            dense = sorted([(e, sum(a*b for a, b in zip(vector, v, strict=True)))
                            for e, v in zip(documents, vectors, strict=True)],
                           key=lambda item: (-item[1], item[0].source_id))
            dense = [(e, s) for e, s in dense if s > 0]
            sparse = index.search([(query, 1)])
            for channel, ranked in [('lexical', sparse), ('dense', dense)]:
                for rank, (entry, similarity) in enumerate(ranked[:24], 1):
                    sid = entry.source_id
                    scores[sid] = scores.get(sid, 0) + weight / (60 + rank)
                    detail = details.setdefault(sid, dict(source_id=sid, evidence_kind=entry.kind))
                    detail[channel + '_rank'] = min(rank, detail.get(channel + '_rank', rank))
                    if channel == 'dense':
                        detail['cosine'] = max(similarity, detail.get('cosine', -1))
        # Evidence-aware tie-break only: actual activity facts before declarations.
        # No scope/qualification inference, negative facts remain retrievable.
        def activity(e):
            return e.kind in {'experience', 'project', 'verified_skill'} and ':technology:' not in e.source_id
        ranked = sorted([(e, scores[e.source_id]) for e in documents if e.source_id in scores],
                        key=lambda item: (-item[1], -activity(item[0]), item[0].source_id))
        diagnostic = {'method': 'local_bm25_dense_rrf', 'embedding_status': 'ready',
                      'model': settings.embedding_model, 'model_revision': settings.embedding_model_revision,
                      'cache_hit': cached, 'rrf_k': 60,
                      'candidates': [RankedEvidence(score=s, **details[e.source_id]).model_dump()
                                     for e, s in ranked]}
        return ranked, diagnostic
    except Exception:
        # No exception text: provider errors can contain candidate input.
        return lexical, diagnostic


async def prepare_inventory_retrieval(inventory, settings):
    """Advisory F-ID hints; the full evidence catalog stays available to analysis."""
    if not settings.hybrid_retrieval_enabled:
        return
    documents = list(inventory.evidence.values())
    ids = {entry.source_id: fid for fid, entry in inventory.evidence.items()}
    # One embedding batch across passages, then per-passage ranking uses cached
    # corpus vectors. Limit hints to genuinely assessable passages.
    from app.services.ollama_analysis import needs_assessment
    inventory.retrieval_hints = {}
    passages = {pid: passage for pid, passage in inventory.passages.items() if needs_assessment(passage)}
    if not passages:
        return
    _, diagnostic = await retrieval_in_thread(
        hybrid_search, documents, [(p['text'], 1.0) for p in passages.values()], settings)
    if diagnostic['embedding_status'] != 'ready':
        return
    for pid, passage in passages.items():
        ranked, diagnostic = await retrieval_in_thread(
            hybrid_search, documents, [(passage['text'], 1.0)], settings)
        inventory.retrieval_hints[pid] = [ids[e.source_id] for e, _ in ranked[:8]]
        if diagnostic['embedding_status'] == 'unavailable':
            break  # One failure, no repeated model discovery/timeouts per passage.


async def retrieval_in_thread(function, *args, **kwargs):
    """Keep an owning provider semaphore held until cancelled HTTP work finishes.

    Python cannot kill a worker thread. Releasing a semaphore immediately on
    cancellation would allow chat inference to overlap its still-running embed.
    """
    import asyncio
    task = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass  # Cancellation must not turn into a recoverable provider error.
        raise
