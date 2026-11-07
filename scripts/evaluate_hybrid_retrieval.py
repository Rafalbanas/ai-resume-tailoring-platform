"""Synthetic deterministic plumbing evaluation; NOT embedding model accuracy.

Run: .venv/bin/python scripts/evaluate_hybrid_retrieval.py
No private data, model server or external provider is used.
"""
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.config import Settings
from app.services.fact_catalog import FactEntry
from app.services.fact_retrieval import FactIndex
from app.services.hybrid_retrieval import hybrid_search


class FakeEmbeddings:
    def embed_documents(self, texts):
        return [[1., 0.] if any(t in text.lower() for t in ('ollama', 'language models', 'modeli językowych'))
                else [0., 1.] for text in texts]


def main():
    documents = [FactEntry('project:one', 'project',
                           'Built a FastAPI application integrating local Ollama inference through HTTP endpoints.'),
                 FactEntry('experience:two', 'experience', 'Handled customer tickets.')]
    queries = ['Experience integrating AI language models into backend applications',
               'Integracja modeli językowych z aplikacjami backendowymi']
    cfg = Settings(_env_file=None, hybrid_retrieval_enabled=True, embedding_model='deterministic-fake')
    totals = {'lexical': 0, 'hybrid_fake': 0}
    citations_valid = True
    tracemalloc.start()
    start = time.perf_counter()
    for query in queries:
        lexical = FactIndex(documents).search([(query, 1)])
        hybrid, _ = hybrid_search(documents, [(query, 1)], cfg, embeddings=FakeEmbeddings())
        for label, ranked in [('lexical', lexical), ('hybrid_fake', hybrid)]:
            totals[label] += int(bool(ranked) and ranked[0][0].source_id == 'project:one')
            citations_valid &= all(entry in documents for entry, _ in ranked)
    elapsed = time.perf_counter() - start
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    print(json.dumps({'dataset': 'two synthetic synonym/translation cases; fake vectors encode relevance',
                      'queries': len(queries), 'recall_at_1': {k: v / len(queries) for k, v in totals.items()},
                      'citation_ids_valid': citations_valid, 'elapsed_seconds': round(elapsed, 6),
                      'python_peak_bytes': peak,
                      'real_embedding_quality_measured': False}, indent=2))


if __name__ == '__main__':
    main()
