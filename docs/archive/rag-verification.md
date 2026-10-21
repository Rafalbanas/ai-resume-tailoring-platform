# RAG verification — 2026-10-18

All automated scenarios use synthetic candidate data. No live LLM quality benchmark or production deployment was performed.

Completed checks:

- `pytest -q tests/test_fact_retrieval.py`: **13 passed**. Includes Technical Support Engineer versus AI/Python Developer selection; additions/deletions in a profile; separate candidates with the same project name; no results; search failure; injected instructions and unsupported Kubernetes claims; source budgeting; empty corpus; skill eligibility; mocked Gemini/Ollama payloads; saved provenance.
- `pytest -q tests/test_tailoring_priorities.py tests/test_gemini_provider.py tests/test_ollama_provider.py tests/test_ollama_token_budget.py`: **60 passed**, one existing Starlette/httpx deprecation warning.
- `pytest -q tests/test_fact_retrieval.py tests/test_storage.py tests/test_tailoring_priorities.py`: **22 passed**.
- `pytest -q tests/test_auth_boundary.py -x` outside the restricted sandbox: **38 passed**, one existing Starlette/httpx deprecation warning.
- `pytest -q tests/test_summary_confirmation.py::test_confirmed_natural_summary_exports_real_pdf_and_docx_and_invalidates_after_edit`: **1 passed**; verifies retrieval trace propagation through the export route alongside actual PDF/DOCX and summary confirmation checks.
- After adding server-side source snapshots: `pytest -q tests/test_fact_retrieval.py tests/test_gemini_provider.py tests/test_ollama_provider.py`: **32 passed**; confirms snapshots survive profile edits and do not add duplicate retrieval text to model requests.
- `ruff check .`: passed.
- `python scripts/check_environment.py --dev`: environment matches the Docker runtime and pinned dependencies.
- `python -m pip check`: no broken requirements.
- `python scripts/sync_readme.py --check`: passed; **799 collected tests**.
- `git diff --check`: passed.

The initial full-suite run inside the restricted sandbox stopped making progress at the first TestClient authentication test and was terminated. The completed full-suite run outside that sandbox (`pytest -q`) returned **797 passed, 2 failed, 1 warning in 983.68 seconds** (799 tests). Both failures were processing deadlines: the long PDF test below and the browser main-page test. The warning is the existing Starlette/httpx deprecation. The source-snapshot addition was subsequently checked with the 32-test focused provider/retrieval run listed above. The long-document test `tests/test_audit_safety.py::test_ats_preserves_long_text_and_reading_order` exceeded the existing 60-second processing limit on both the changed checkout (68.31 s) and a separate pristine HEAD copy in `/tmp/cvtailor-rag-baseline` (66.79 s). No renderer or processing timeout was changed as part of RAG. The browser security test `test_all_browser_pages_block_requests_to_private_services[main-page]` passed in isolation on pristine HEAD (12.68 s) and the changed checkout (10.60 s), after failing in the full run. Browser/security code was not changed. Docker image builds and production deployment are outside this local verification.

The private project profile was updated by appending three implementation facts. Its Pydantic schema and the existing skills bank evidence references were validated; existing facts, description, owner and permissions were retained. It is git-ignored and is not part of the public patch. No existing CV export or application history was changed.
