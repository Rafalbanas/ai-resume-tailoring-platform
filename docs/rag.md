# Candidate fact retrieval and RAG

## Audit (2026-10-18)

No `AGENTS.md` was present in the checkout or its parent directories. Project checks are specified in `CONTRIBUTING.md` and `.github/workflows/ci.yml`.

Before this change, CVTailor already had important grounding components, but no bounded candidate-fact retrieval context for CV generation:

- `load_master_profile` (`app/services/profile_loader.py`) loads canonical candidate facts; `SkillsBank` validates skill evidence and eligibility.
- `FactCatalog._build` (`app/services/fact_catalog.py`) creates content-derived IDs for individual facts, project descriptions/technologies, education and skills. This is a source catalog, not by itself retrieval.
- `build_compact_analysis_payload` (`app/services/ai_provider.py`) supplied the full professional profile/catalog to Gemini. `AnalysisInventory.build` (`app/services/ollama_analysis.py`) supplies indexed evidence for Ollama analysis with batching. Numbering evidence and batching it to fit a context window are not candidate retrieval.
- `EvidenceMatcher` (`app/services/evidence_matching.py`), `AnalysisValidator.validate`, and semantic requirement checks deterministically validate scope and supporting sources. They already perform evidence lookup/matching for requirement assessment. This is useful grounding; it did not restrict the CV generator's candidate context.
- `build_compact_tailor_payload` supplied all experience/project facts, while `GeminiProvider.tailor_resume` and `OllamaProvider.tailor_resume` built a complete `FactCatalog`. The LLM selected facts from that full context.
- `ReferenceCVLibrary.select` already retrieved reference CVs for style. These documents are explicitly not candidate evidence.
- `FactValidator.validate` and the export routes (`app/routes/web.py`) enforce Truth Lock independently of the prompt, with a separate summary review/attestation mechanism.

The implemented change is **lexical RAG for the CV generation stage**: retrieve canonical facts in Python, then supply that selected source context to the generator. Analysis deliberately continues to assess all evidence so that a retrieval miss cannot become a false claim of a missing qualification. Mock and legacy n8n webhook providers retain their existing behavior; this implementation covers direct Gemini and Ollama generation, including switching between them through the resilient router.

## Documents and index lifecycle

`retrieve_facts` in `app/services/fact_retrieval.py` builds a fresh `FactCatalog` from the **profile argument of that request**. Each fact is a document; no sentence is cut in half. Project descriptions and technology declarations, individual skill declarations, summary facts, education identity/facts/thesis and certifications retain their original source IDs, type, owner name and owner index. Interests are excluded. SkillsBank, when available, filters skill documents through its existing `eligible` policy; learning, disabled, unverified or disallowed skill entries do not become eligible via retrieval. Explicit learning declarations remain handled by the existing separate Currently learning flow.

Employment stays `experience`, personal/project work stays `project`, and academic work stays `education`. A project technology declaration is evidence of that declaration only; it proves neither commercial tenure nor advanced proficiency. Profile facts are trusted as saved candidate attestations, not independently verified against external documents. Supporting evidence descriptions for eligible skills remain available through the existing skills bank payload; they are not an additional cross-user corpus.

There is no persisted index or shared retrieval cache. Profile edits, additions and deletions therefore take effect on the next generation request without invalidation jobs. Old in-flight requests keep their own snapshot. Direct edits to the JSON file follow the existing application profile-loading lifecycle; retrieval adds no filesystem watcher or live reload. Each trace contains a SHA-256 revision of the indexed documents. That revision is diagnostic metadata, never a cache key or authorization token. Retrieval cannot load another candidate's files or perform a global search: it only sees the supplied profile. The application remains a single-owner application with its existing account/routing boundaries.

## Search, ranking and context

`FactIndex` implements BM25 in the Python standard library (`collections.Counter`, `math`) with `k1=1.2`, `b=0.75`. It reuses `normalized_tokens` from the catalog: case folding, accent normalization and stop-word filtering. Token frequencies, document frequencies and average document length are computed locally. Owner/title metadata is returned for provenance but is not added to document search text, so a project title does not make every fact a match.

Queries are requirement names from validated analysis plus role competencies. Mandatory requirements have weight 2, other requirements/competencies weight 1; the advertised role has weight 0.5. Each query's BM25 contribution is divided by its token count, then contributions are summed. If analysis has no requirements/competencies, the original job description becomes a query. This fallback may include noisy employer language. Model-suggested source IDs never cause a fact to be selected automatically. Ties use source ID for deterministic ordering.

Defaults are code constants `TOP_K=24` and `MAX_CONTEXT_CHARS=16000`. `retrieve_facts` also accepts keyword overrides for testing/callers; there are no additional environment settings. The ranker considers the top 24 matches and adds whole facts within a 16,000-character source-text budget. It always retains the first summary fact, one actual employment fact per role, and each main education identity to preserve chronology and identity. These anchors may exceed the budget in a very large profile, and are additional to the ranked limit. The budget is not a token limit and does not count JSON, job text, skills metadata, repeated grouped source views or model output. An oversized individual non-anchor fact is skipped rather than truncated.

`build_compact_tailor_payload` supplies only these selected facts in `source_catalog` and grouped `candidate_facts`, with employment identity metadata and selected project links. Eligible skill wordings remain constrained by the existing bank. Both providers receive the same selected catalog; Ollama also uses it to constrain source-ID schema enums. Gemini's JSON schema does not itself enforce source membership; Truth Lock remains mandatory. Original job text and requirement assessment remain present and explicitly separate from candidate evidence.

No embeddings, vector database, extra service, paid retrieval API, model download or additional dependency is used. Index construction costs memory proportional to source tokens; search scans documents for each query. This suits small per-candidate profiles on a VPS, not a large document collection. Vocabulary differences, synonyms, translation and long multi-topic facts can reduce lexical recall. The tokenizer has no general stemming or semantic understanding. No improvement in match quality, latency or resource consumption has been measured.

## No hits, failures and Truth Lock

No positive lexical hits gives mode `no_matches`: keep identity anchors and let the existing skill/Truth Lock rules apply. It does not manufacture evidence for the missing technology. An index/search exception gives `catalog_fallback`: use the current candidate's canonical catalog, retaining the same skill filtering and export validation. Logs contain a generic warning, with no candidate facts or exception text. Fallback can increase prompt size; provider context/budget checks still apply. Invalid profile/skills configuration is not silently replaced with another candidate or an example profile.

All job text, retrieved text, owners and reference documents are untrusted **data**, never system instructions. Relevance scores are not proof of competence. Existing rules still reject unknown skills, proficiency inflation, unsupported claims and project-to-employment promotion. Retrieval does not change `FactValidator`, skill eligibility, summary attestation, or the manual/export review boundary. Final validation can restore canonical facts omitted from generation context to preserve required sections and safe wording; retrieval is not a security allowlist for final output.

## Provenance and example

`TailoredResume` keeps a private server-populated trace; `WorkflowResponse.retrieval_context` carries it into new saved drafts. New application metadata also stores that trace. It includes method, mode, index revision, queries/weights, document count, limits and selected source IDs/types/owners/scores/reasons (`lexical_match`, `identity_anchor`, `catalog_fallback`). Direct providers also attach a snapshot of the selected source catalog (including full fact text) to the server-side trace after generation, without sending another copy to the LLM. This preserves the source context when the profile is edited later. The trace is diagnostic, not a signed attestation. Existing exports and historical applications are not migrated or rewritten. Final resume JSON still contains `summary_source_fact_ids` and source IDs on experience bullets, projects and education. Resolve those against `FactCatalog` to inspect the actual supporting facts. Core skills continue to use bank IDs/evidence. The generation snapshot preserves retrieved facts after profile edits. Facts later restored by validation or introduced through validated manual edits may be outside that snapshot; retain the corresponding private source profile to resolve those IDs.

Synthetic tests compare the same candidate:

| Posting query | First ranked fact (`top_k=1`) | Source scope |
| --- | --- | --- |
| Technical Support Engineer: customer tickets, network incidents | Investigates customer tickets and network incidents. | Employment |
| AI/Python Developer: Python, FastAPI, JSON | Builds Python FastAPI services with structured JSON responses. | Personal project |

Both retain basic identity anchors. Adding Kubernetes to the job query adds no Kubernetes source fact. Even if a model emits an invented Kubernetes achievement citing a valid but unrelated source ID, Truth Lock removes/replaces the unsupported wording. This is a regression scenario, not a measured quality benchmark.

## Validation

`tests/test_fact_retrieval.py` covers role-specific selection, source types/IDs, profile edits/deletions, separate candidates sharing project names, no matches, a failed index search, unknown technology and instruction injection, whole-fact budgeting, empty corpus, skill eligibility, both provider payloads and trace persistence in new drafts/application metadata. All inputs are synthetic; provider calls are mocked. See [executed checks and results](rag-verification.md) for the repository checks.
