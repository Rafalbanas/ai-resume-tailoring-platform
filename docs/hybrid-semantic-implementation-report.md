# Hybrid semantic implementation report

## Scope and outcome

Implemented an additive, default-off hybrid retrieval path and an optional bounded
LangGraph analysis path. Existing profile schemas, qualification validators, Truth
Lock, provider routing, export workflows and saved-report contracts are retained.
The initial working tree was clean. No private data/configuration, production
service, model installation, deployment or Git remote was modified.

**Final serial full-suite validation: 1640 passed, 1 skipped, 13 warnings in
1295.68 s (21:35)**, using the isolated Python environment matching the pinned
project dependencies. The skipped test requires an explicitly selected real local
embedding model. Earlier failing broad runs and passing rechecks are retained
below rather than rewritten as successes.

See [technical architecture, setup and limitations](hybrid-semantic-matching.md)
for formulas, model research, safety boundaries and reproducible evaluation.

## Added files

* `app/services/hybrid_retrieval.py`: local LangChain/Ollama embeddings, cosine,
  weighted RRF, source-type tie-break, bounded vector caches, safe lexical fallback,
  advisory analysis hints and cancellation-aware thread offloading.
* `app/services/analysis_graph.py`: actual LangGraph state/conditional workflow,
  existing inventory/validator reuse, one retry, disabled external tracing.
* `requirements-semantic.txt`: optional pinned LangChain Ollama/LangGraph packages.
* `scripts/evaluate_hybrid_retrieval.py`: synthetic deterministic Recall@1/citation/
  allocation/time evaluation, no external model or private facts.
* `tests/test_hybrid_retrieval.py`, `tests/test_analysis_graph.py`, `tests/test_named_semantic_guards.py`,
  `tests/test_hybrid_safety.py`: deterministic unit/integration and safety contracts;
  explicit opt-in local real-model test.
* `docs/hybrid-semantic-matching.md` and this report.

## Modified files

* `app/core/config.py`, `.env.example`: feature/model/endpoint/revision/timeout flags.
* `app/services/fact_retrieval.py`: optional hybrid ranking within existing selection
  budgets, identity anchors, tailoring blending and diagnostic trace.
* `app/services/ai_provider.py`: optional retrieval settings forwarding.
* `app/services/ollama_analysis.py`: typed advisory hints and explicit untrusted-data/
  relevance-only prompt boundary; complete evidence remains available.
* `app/services/indexed_analysis.py`: configurable inner retry count so the graph
  owns its bounded retry rather than multiplying nested retries.
* `app/services/competency_scope.py`, `app/services/evidence_matching.py`,
  `app/services/semantic_requirements.py`: narrow named-product scope guards,
  commercial source qualifiers and relevant employment tenure safeguards.
* `app/services/ollama_provider.py`, `app/services/gemini_provider.py`: optional graph
  dispatch, hybrid hints, thread-offloaded generation retrieval and original-path
  fallback when graph dependencies are absent.
* `README.md`, `docs/architecture.md`, `docs/rag.md`: default-vs-optional clarification
  and link to detailed documentation.

## Diagnosis, not assumptions

| Stage | Finding | Treatment |
| --- | --- | --- |
| Retrieval for generation | No shared tokens between Polish requirement and English implementation fact; BM25 yields no hit | Reproduced; dense candidate discovery + RRF |
| Evidence selection during analysis | Existing model sees all facts; this is not BM25 truncation | Add advisory passage-specific IDs, retain full catalog |
| Extraction/classification | Existing regressions cover source omissions, unfamiliar headings, preferred clauses and duties | Reuse literal inventory/coverage validation and bounded feedback; no new extraction-quality claim |
| Evidence validation | Valid citations to LangChain/LangGraph or Azure AD could confirm a different named product | Reproduced 3 false positives; extend shared scope checks without bypassing validators |
| Export | Retrieved relevance cannot authorize invented claims | Existing FactValidator/Truth Lock and export review unchanged |

The selected existing baseline suite passed, but an additional six-case synthetic
semantic-validation test exposed three wrong-product false positives before the
scope fix; all three same-product controls already passed. After the fix, all six
cases pass, with additional commercial-source and tenure guards. This does not
establish that all historical reported matching errors share one root cause. Embeddings do
not fix priority classification, AND/OR, incomplete source text or unsupported
model claims. No higher qualification-score target was introduced.

## Executed evaluation

Before implementation, the seven focused existing suites passed **137 tests in
10.32 s**. In the original `.venv`, the retrieval/graph-focused run passed
**172 tests, 1 skipped in 21.43 s**. The subsequent environment checker identified
outdated installed pins (FastAPI, Pydantic, settings, pypdf, tokenizers, pytest,
pytest-asyncio, Ruff and jsonschema), so final focused validation used a fresh
isolated `/tmp/opencode/cvtailor-semantic-venv`, matching project requirements.
The final expanded focused run, including named-product and competency-scope
regressions, passed **212 tests, 1 skipped, 13 warnings in 50.37 s**.
The skip requires an explicitly selected, already-installed embedding
model; no real embedding model was available locally.

`python scripts/evaluate_hybrid_retrieval.py` measured two synthetic cases:
Recall@1 lexical **0.5**, hybrid with relevance-encoded fake vectors **1.0**, valid
returned source IDs, **0.010247 s** elapsed and **11,312 bytes** Python peak traced
allocations in that run. This is an integration test, **not** model-quality,
production-memory or latency evidence. Real extraction precision/recall,
mandatory/preferred accuracy, qualification false positives/negatives and real-model
Recall@K remain unmeasured without an annotated representative benchmark.

`ruff check .`, `git diff --check`, `python -m pip check` and the final isolated
`scripts/check_environment.py --dev` passed. Optional dependencies were installed
only in isolated project/validation environments. Third-party LangSmith emitted
13 Python 3.14 deprecation warnings; pytest-asyncio also warns about the existing
unset future fixture-loop default. Read-only model
discovery found no embedding model; no downloads or real LLM analysis were run.

Completed full-suite results are recorded below; intermediate test output was
not treated as a passing full suite.

### Completed first full run and failure recheck

The first `.venv/bin/python -m pytest -q` finished with **1616 passed, 4 failed
in 3961.73 s**. This was the earlier code/test snapshot in the pre-existing,
outdated-pin environment, not a clean final pinned full run. Failures were:

* `test_quick_avatar_replaces_removes_and_returns_to_initials`: HTTP 422 instead of 200.
* `test_preview_and_draft_links_stay_in_their_account_before_exports_finish[owner]`:
  preview returned HTTP 422 after approximately the document-worker deadline.
* `test_browser_shared_login_password_paste_and_account_bound_requests`:
  Chromium startup exceeded 180 seconds.
* `test_preview_pages_match_pdf_and_do_not_mutate_saved_resume`:
  document preview worker exceeded 60 seconds.

All four were then run together against the current code with the pinned isolated
interpreter: **4 passed, 13 warnings in 310.66 s**. No application timeout, test
assertion or export implementation was relaxed to achieve this. The failure was
not reproduced in that focused recheck; resource contention, earlier dependency
versions or full-suite interactions remain possible causes, not proven diagnoses.
A failed full run plus passing focused rechecks is **not** reported as a passing
full run. A separate final serial pinned full run was therefore performed.

The pinned full run subsequently completed with **1634 passed, 2 failed, 2 setup
errors, 1 skipped, 13 warnings in 3988.27 s**. The failed learning-export test
reported the unchanged 60-second document-worker timeout; the custom-editor
navigation failed at its 30-second browser deadline. Both setup errors were
Chromium launch timeouts at 180 seconds. Those four exact cases were then run
together with the same pinned interpreter after all broad runs ended:
**4 passed, 13 warnings in 35.80 s**, without code/timeout/assertion changes.

The final current-code full run was launched **alone**, with no competing full
or focused test suites, and completed successfully:

```sh
/tmp/opencode/cvtailor-semantic-venv/bin/python -m pytest -q --tb=short
# 1640 passed, 1 skipped, 13 warnings in 1295.68s (0:21:35)
```

No application timeout, test assertion or export implementation was changed
between the failing broad runs, focused rechecks and successful serial run.
This supports sensitivity to execution conditions; it does not isolate a single
causal factor or establish production performance. The successful final run does
not erase the earlier failed results.

The additional older-environment run excluding `tests/test_custom_cv.py` finished
with **1583 passed, 6 failed, 1 skipped in 4343.81 s**. Failures concerned
`test_generated_modern_pdf_one_page_keeps_levels_and_learning`, two quick-photo
tests (`test_quick_avatar_replaces_removes_and_returns_to_initials`,
`test_real_jpeg_portrait_upload_end_to_end`) and three
`test_pdf_reserved_consent_never_forms_own_page` variants. Its document-worker
tracebacks include the unchanged 60-second processing limit. The broad runs
partially overlapped; contention may have affected timing-dependent checks, so
their wall times are not application performance benchmarks. No further full
parallel run is launched. These failures remain recorded, not hidden by retries.

The final cancellation/error-path and multi-batch coverage additions were also
checked directly with the pinned interpreter: **3 passed, 13 warnings in 15.70 s**
(`test_cancelled_retrieval_waits_for_owning_thread`, two variants, and
`test_graph_preserves_coverage_when_existing_planner_splits_batches`). The later
expanded focused command hit its 120-second deadline before a summary, so it is
not counted as a completed aggregate run.

## Direct before/after comparison (same inputs and pinned interpreter)

The committed baseline `590f648` was extracted with `git archive HEAD` into a
separate temporary directory, without copying ignored profiles, secrets or data.
The identical new named-product regression file was then run against that code
and against the working implementation, using the same pinned Python environment:

```sh
python -m pytest -q tests/test_named_semantic_guards.py -k related_named_product_cannot --tb=short
```

| Synthetic source/requirement | Baseline | Current |
| --- | --- | --- |
| LangChain implementation cited for LangGraph experience | Incorrectly confirmed | Not confirmed |
| LangGraph implementation cited for LangChain experience | Incorrectly confirmed | Not confirmed |
| Azure Active Directory implementation cited for Azure AI Services | Incorrectly confirmed | Not confirmed |
| Three corresponding same-product positive controls | All 3 confirmed | All 3 confirmed |

Actual results: baseline **3 failed, 3 passed, 3 deselected**; current **6 passed,
3 deselected**. Thus the targeted validation false positives decreased from **3
to 0**, retaining all **3** positive controls. This is a demonstrated narrow
correctness improvement, not a claim of population-level precision/recall.
Baseline/current durations (16.18/19.79 s) are not a controlled performance test:
other full suites were active and the validation now performs additional checks.

An independent junior comparison of `tests/test_hybrid_safety.py` was then
re-run by the senior with the same pinned interpreter against both code versions:
**4 passed before and 4 passed after** (30.52/30.70 s in those loaded-system runs).
The asserted B2-versus-C1, project-versus-employment-tenure and Python/Kubernetes
AND/OR safeguards retain their previous behavior. No unasserted match-level
detail from a review narrative is treated as an additional measured result.

The retrieval evaluator was re-run with the pinned interpreter: lexical Recall@1
**0.5**, hybrid-fake **1.0**, valid citations; 0.018488 s and 11,951 traced Python
peak bytes in that run. No conclusion about real embedding or LangGraph quality
can be drawn from fake vectors or successful workflow tests. A real local-model
comparison remains blocked by the absence of an installed embedding model; no
model was downloaded automatically.

The older-environment and first pinned broad failures were reviewed and recorded
above; they are not reported as passing. The final serial pinned full run passed.
Do not promote this change to production on the strength of the narrow quality
comparison alone: real local-model evaluation remains outstanding.

An additional broad safety/export command in the older `.venv` reached the
120-second command deadline without a test summary; it is **not counted as a
passing run**. The first fresh-environment installation also hit that deadline
and completed successfully on a subsequent cached installation attempt. No
production process or service was interrupted.

## Safe local acceptance before deployment

### PR integration on the updated main branch

Before publishing the PR, the implementation was rebased onto `origin/main`
`37c0807`, which includes subsequent project-evidence, education, source-scope,
history and budget changes. The semantic-validator conflict was resolved by
preserving main's literal-example queries, degree recovery and ticketing guards
alongside the new named-product/commercial-scope checks. No main features were
reverted. Post-rebase verification passed **202 tests, 1 skipped, 13 warnings in
10.76 s**, covering all four new suites plus existing retrieval, evidence,
LLM-first analysis, source-scope contracts, education recovery, project-first CV
quality, source metadata and reason idempotency suites. The 1640-test full result
above belongs to the implementation before this rebase, not a full rerun on the
new main. The PR is opened as a draft pending broad CI/current-base verification
and real local-embedding evaluation. Nothing is merged or deployed.

1. Use synthetic data and a separate development runtime; disable cloud fallback.
2. Run the tests/evaluator documented in the technical guide.
3. Install optional requirements only when testing the optional path.
4. Select an already-installed loopback embedding model and explicit revision.
5. Compare both flags off, hybrid only, and hybrid + graph on the same fixtures.
6. Inspect literal requirements, priority, provenance, project/employment scope,
   negations, language levels, dates and final Truth-Locked exports, not just ranks.
7. Benchmark cold/warm model latency and OS memory before considering deployment.

Disable `HYBRID_RETRIEVAL_ENABLED` and `ANALYSIS_GRAPH_ENABLED` to restore the
original path. Model provisioning and production promotion remain operator tasks.
