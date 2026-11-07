# Optional hybrid semantic matching

## Boundaries and architecture

This is an additive, **default-off** extension, not a replacement for extraction,
qualification validation or Truth Lock. No private profile or skills file is changed.

1. Portal adapters normalize the advertisement. `job_sections.py` preserves literal
   passages, headings, priorities and AND/OR scope.
2. `AnalysisInventory` supplies the entire candidate evidence catalog and literal
   passage IDs to the existing Ollama/Gemini interpretation schemas.
3. Optional hybrid retrieval adds advisory per-passage F-ID hints. **All evidence
   remains available**: a retrieval miss is not a qualification gap.
4. `AnalysisValidator`, `semantic_requirements`, `grounded_requirements` and
   `EvidenceMatcher` remain authoritative for citations, source coverage,
   language levels, relevant dated employment, negations and scope ceilings.
   Shared scope checks now explicitly separate LangChain, LangGraph and Azure AI
   Services. A valid citation to a related product cannot confirm the requested one;
   personal projects cannot establish commercial scope or employment tenure.
5. Separately, generation retrieves candidate facts with existing identity anchors,
   SkillsBank filtering, top-24 and 16,000-character whole-fact budget. Hybrid mode
   can change the ranking, not the facts. Identity anchors retain their existing
   budget exception. Tailoring-level blending remains available.
6. FactValidator/Truth Lock, summary confirmation, PDF/DOCX and history are unchanged.

`hybrid_retrieval.py` uses the existing `FactIndex` BM25 and the lazy
`langchain_ollama.OllamaEmbeddings` adapter. Owner and source kind are included in
document embedding context. Unit-normalized vectors use cosine similarity.
Positive-cosine top-24 dense and BM25 rankings are combined per query with weighted
reciprocal rank fusion: `weight / (60 + rank)`. Mandatory queries retain weight 2,
other queries 1, role 0.5. Actual activity facts beat technology/declaration rows
only on fused-score ties. This deliberately modest evidence-aware tie-break does
**not** prove practice, commercial scope, proficiency or positive sentiment.
Negative evidence is not filtered from retrieval.

Pydantic `RankedEvidence` exposes source ID, lexical/dense rank, cosine, fused
score and kind. Generation's existing retrieval trace additionally records method,
model/revision, cache hit and fallback status. These are relevance diagnostics,
not qualification scores or signed attestations. Treat saved diagnostics like
the existing private CV history, not public telemetry.

## Cache, privacy and failure behavior

The process-local LRU contains hashes and vectors, not raw text. Its key includes
the full ordered source IDs/text/kinds/owners, endpoint, model, explicit model
revision and rendering version. Changes/deletions and different candidates cannot
reuse stale content under a matching project title. At most four corpora and one
million corpus scalar values are retained, plus 128 query vectors. Dimensions are
bounded to 2,048; input to 512 documents/128,000 source characters and 128 queries/
64,000 query characters. This is not a vector database. No disk index or service
is introduced. Cache lifetime is process lifetime/LRU eviction; restart to clear.
Bump `EMBEDDING_MODEL_REVISION` when replacing a model under the same tag.

Only explicit loopback HTTP(S) embedding endpoints are accepted. HTTP proxy
environment variables and redirects are disabled. There is no external embedding
API, automatic model download, or sensitive exception logging. LangGraph tracing
is explicitly disabled, even if LangSmith tracing is configured in the host.
Existing Gemini selection/fallback can still send analysis data externally;
disable provider fallback for local-only testing.

Missing optional dependency/model, invalid/non-finite/zero/dimension-mismatched
vectors, oversized input or embedding errors return the **exact lexical ranking**.
Hybrid hints are omitted on failure, without retrying every passage. The existing
catalog fallback remains for lexical-index failure. Document/query vectors are
batched and cached; embedding work is serialized per process. Direct Ollama calls
share that provider's semaphore with embedding preparation. Async provider paths
offload synchronous retrieval to a thread. No background embedding jobs survive
normal completion. Different processes, independently constructed providers and
Gemini/Ollama operations do not share a cross-process Ollama scheduler; avoid
parallel analysis workers on a small VPS. HTTP timeouts are per request, not an
extra global inference budget, and synchronous low-level callers may block.

## Small LangGraph alternative

`analysis_graph.py` uses actual `StateGraph`, `START`, `END` and conditional edges,
with request-local `TypedDict` state and no checkpointer, agent or persistent store:

`prepare_job -> retrieve_candidate_evidence -> extract_requirements ->`
`validate_requirements -> validate_evidence -> finalize_analysis`

Retrieval happens before the model interpretation because hints need literal
passage IDs, not an unvalidated model paraphrase. Existing `plan_batches`,
`indexed_interpretation`, inventory citation/coverage validation and
`AnalysisValidator` are reused. Requirement and evidence validation stay combined
inside the existing validator; the evidence node routes its result rather than
duplicating safety rules. Source coverage, ambiguity and unsupported claims cause
one feedback-guided retry of the planned batches. Recoverable response/availability
errors also get at most one retry; internal indexed retries are disabled here.
Persistent provider/citation errors raise the normal provider error; a final
unreliable report stays unreliable. Two extraction passes and recursion limit 16
bound graph execution. Existing outer provider budgets/fallback still apply.

This optional path deliberately does **not** replace Ollama's mature targeted
partial-batch recovery. It may repeat completed batches and has no measured
quality or latency advantage. Use it for controlled comparison, not as a presumed
upgrade. Absent LangGraph, the original orchestrator remains functional. No public
request/response fields or historical reports are migrated.

## Model choice and local setup

Investigated upstream model cards (2026-11-06):

* [EmbeddingGemma](https://ollama.com/library/embeddinggemma): 300M parameters,
  622 MB artifact, 2K context, training in 100+ languages, Ollama >=0.11.10.
  Recommended first small multilingual PL/EN candidate, **not locally benchmarked**.
* [Qwen3 Embedding 0.6B](https://ollama.com/library/qwen3-embedding:0.6b): 639 MB,
  multilingual/code retrieval alternative. Larger family members are unnecessary
  here and some exceed the vector dimension guard.

Read-only local `/api/tags` discovery found generation models but no embedding
model. Nothing was downloaded and no inference model was changed. Choose only
an already provisioned embedding model; obtain explicit operator approval before
any download. Polish retrieval quality and real VPS memory/latency remain unmeasured.
Long facts may exceed a model's context and be truncated by its embedding API;
the original complete fact is always retained for validation. Task-specific
embedding prefixes and splitting long facts are future evaluation work.

In an isolated environment with synthetic data:

```sh
.venv/bin/python -m pip install -r requirements-semantic.txt
# Inspect installed local models only; this does not download anything:
curl http://127.0.0.1:11434/api/tags
```

Set environment flags (or the development `.env`, never a production secret file):

```dotenv
AI_PROVIDER=ollama
LLM_PROVIDER=ollama
LLM_FALLBACK_PROVIDER=none
HYBRID_RETRIEVAL_ENABLED=true
EMBEDDING_MODEL=embeddinggemma
EMBEDDING_MODEL_REVISION=1
EMBEDDING_BASE_URL=http://127.0.0.1:11434
EMBEDDING_TIMEOUT_SECONDS=10
ANALYSIS_GRAPH_ENABLED=false
```

The example model must already exist; an unavailable tag safely falls back. Compare
the same synthetic profile/posting in three fresh development processes:

| Mode | Hybrid flag | Graph flag |
| --- | --- | --- |
| Existing | false | false |
| Hybrid + original orchestration | true | false |
| Graph-assisted hybrid | true | true |

Flags are startup configuration, not per-user mutable state. Set both to false to
restore the original path; optional packages need not be installed. Never enable
Gemini just to test embeddings. Never use real candidate data in a benchmark.

## Diagnosis and reproducible evaluation

Baseline before code changes: 137 existing targeted tests passed in 10.32 seconds
(`fact_retrieval`, `evidence_matching`, `analysis_matching_regressions`,
`indexed_analysis`, `llm_first_analysis`, `source_qualification_guards`,
`source_disposition_regressions`). Existing fixtures already guard preferred vs
mandatory, responsibility classification, compound conditions, conflicting facts,
injection and incomplete source disposition.

Confirmed retrieval cause: normalized BM25 token overlap misses the synthetic
Polish requirement `Integracja modeli językowych z aplikacjami backendowymi` for
an English FastAPI/Ollama implementation fact. Adding embeddings fixes candidate
discovery with deterministic fake vectors. It does not establish real-model recall.
An additional six-case named-product test reproduced **three false-positive
confirmations** before the scope fix (LangChain for LangGraph, the reverse, Azure
AD for Azure AI Services), while all three same-product controls passed. The
shared scope guards now reject all three wrong-product citations and retain all
three positive controls. Additional tests protect commercial source qualifiers
when the model returns a shortened label, and named-product employment tenure.
These are specific deterministic regressions, not population-level accuracy.

Analysis already sees all facts: overlooked projects there are an interpretation/
citation-selection problem, **not** a truncated BM25 catalog. Per-passage hints
address discoverability, but a measured reduction in LLM omissions is not claimed.
The existing inventory retries and validators expose missing coverage, prevent
project tenure/B2 elevation and distinguish absent from unconfirmed. Embeddings
cannot repair classification, ambiguous AND/OR or unsupported citations.

```sh
.venv/bin/python scripts/evaluate_hybrid_retrieval.py
.venv/bin/python -m pytest -q tests/test_hybrid_retrieval.py tests/test_hybrid_safety.py tests/test_analysis_graph.py tests/test_named_semantic_guards.py
.venv/bin/python -m pytest -q
.venv/bin/ruff check .
.venv/bin/python -m pip check
# Optional real integration: only an already-installed model, synthetic text:
CVTAILOR_TEST_EMBEDDING_MODEL=embeddinggemma .venv/bin/python -m pytest -q tests/test_hybrid_retrieval.py -k optional_real
```

The two-case deterministic evaluation measured Recall@1 **0.5 lexical vs 1.0
hybrid-fake**, all returned citations valid, 0.010247 s combined elapsed and 11,312
Python peak traced bytes in one run. Fake vectors intentionally encode relevance:
this proves fusion/integration behavior, **not** an embedding benchmark, quality
percentage or Ollama runtime/RAM estimate. Re-run to obtain machine-local timings.

New tests cover synonym/PL-EN candidates, fallback/disabled paths, malformed vectors,
cache changes/limits, canonical IDs/duplicates, context budgets, complete evidence
retention, local-only endpoint policy, the real lazy LangChain adapter, graph
coverage/citation failure, persistent validation issues and bounded termination.
Four additional safety tests preserve language, tenure and AND/OR behavior.
`tests/test_named_semantic_guards.py` additionally covers the reproduced valid-ID/
wrong-product validation defect. Existing suites cover other related-technology false positives, preference/duty priority,
negations, injection and Truth Lock independently of retrieval scores.

The final full suite, run alone in an isolated environment matching the repository's
pinned dependencies, passed **1640 tests, with 1 optional real-model test skipped
and 13 third-party deprecation warnings, in 1295.68 seconds**. Ruff, dependency
consistency, the project environment checker and diff whitespace checks also
passed. Earlier broad runs experienced browser/document timeouts; their actual
failures and successful focused rechecks are preserved in the
[implementation report](hybrid-semantic-implementation-report.md).

That full result predates the PR rebase onto updated main; see the report's PR
integration section for the newer-base targeted results and remaining verification.

Extraction precision/recall, priority classification accuracy, qualification false
positives/negatives and real-model Recall@K are **not measured**: there is no new
annotated representative PL/EN benchmark or available local embedding model.
Before deployment, annotate literal requirements/priority, acceptable source IDs,
dangerous negatives and scope; freeze evaluation date and model digest; compare
all three modes on identical synthetic cases. Report retrieval recall separately
from validated qualifications and source citation correctness. Review false
positives manually. Measure cold/warm inference time and OS RSS separately from
Python allocation measurements. Production promotion remains an operator decision.

The named-product guards are intentionally narrow, not a complete product ontology
or semantic entailment engine. Other unusual competencies still depend on the
existing model interpretation plus validator ceilings and human review. Retrieval
does not make that reasoning infallible; never interpret the synthetic tests as a
guarantee that every valid-looking citation entails every possible qualification.
