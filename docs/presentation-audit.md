# Presentation audit and implementation report

Audit date: **2026-11-13**. Base: `4c35b86` (current fetched `main` at audit time).
This report describes repository inspection and this presentation change, not a
new production audit or a claim of complete application correctness.

## Scope and safeguards

- Read the full former README; inspected the documentation index, setup,
  architecture, deployment/K3s, runtime images, processing security, retrieval,
  optional hybrid, manual editing, offline export and recording documentation.
  Historical reports were treated as revision-specific evidence, not rerun results.
- Inspected tracked structure/configuration, all CI/CD workflows and community
  templates. Traced startup/settings, provider routing, mock generation,
  FactValidator, draft export, HTML export and the relevant synthetic regressions.
- Inspected fictional screenshots, both template comparisons and recording
  provenance. The recording notes explicitly report an in-app export timeout;
  no new successful video or real-model run is claimed here.
- Queried repository description, topics, license and release listing read-only
  with authenticated GitHub CLI. No published release was returned. Branch
  protection, enabled private-reporting settings and live infrastructure were not audited.
- Existing local uncommitted application/README changes were left in their
  original worktree. This feature branch uses a separate worktree based on fetched
  `main`; it does not stage those local changes.
- **All infrastructure configuration is read-only:** no Kubernetes manifests,
  Docker/Compose configuration, deployment scripts, CI/CD workflows, ingress,
  networking, storage, RBAC, backup or production-secret changes. Existing K3s
  documentation is unchanged. No production-changing command or deployment
  workflow was triggered.

## First-visit assessment

| Visitor | Strength | Friction before this change | Highest-value response |
|---|---|---|---|
| Developer | Source-grounded Python validation, direct LLM providers, substantial tests | 600+ line README opens like an internal engineering report; setup arrives late | Put proposition, authentic visuals, runnable mock path and contributor links first |
| Job seeker | Explicit gaps, evidence-linked skills and editable exports | Production-first configuration, multiple secrets, unclear distinction between report and exported CV | Synthetic local walkthrough, generated secrets, honest privacy/export boundaries |
| Technical recruiter | FastAPI, Ollama/Gemini, document engines, K3s/RBAC/backup and CI/CD | Engineering depth obscures the product story; absolute-sounding claims undermine credibility | Compact architecture and stack with links to implementation evidence, not benchmark claims |

## Verified differentiators and boundaries

| Capability | Implementation / evidence | Accurate presentation |
|---|---|---|
| Structured backend | `app/main.py`, `app/models/`, `app/routes/` | FastAPI/Pydantic/Jinja2 with authenticated workflows |
| Direct local/cloud AI | `ollama_provider.py`, `gemini_provider.py`, `resilient_provider.py` | Structured generation, operation budgets and optional fallback; cloud fallback affects privacy |
| Fact retrieval | `fact_catalog.py`, `fact_retrieval.py`, `hybrid_retrieval.py` | Default lexical BM25; local embeddings and LangGraph explicitly optional/default-off |
| Truth Lock | `fact_validator.py`, skills bank and summary-review services | Independent source/level/scope checks, not external verification or zero-hallucination protection |
| Documents | `pdf_generator.py`, `docx_generator.py`, `html_resume.py` | Two PDF/HTML themes, editable DOCX and offline HTML/ZIP; format/layout limits disclosed |
| Failure handling | `draft_export.py`, artifact transaction services | Staging/rollback avoids presenting partial exports as completed CVs |
| Security | Auth/session/CSRF, URL transport, processing services and security regressions | Layered controls with deployment-dependent boundaries; no encryption-at-rest or SaaS guarantee |
| Infrastructure | Existing K3s manifests, RBAC, storage, backup/monitor and CD documentation | Preserved core engineering value; Compose remains an alternative, not a replacement |
| Automation | Batch API and optional n8n | Explicitly supplied offers, not discovery/crawling or automated applications |

The main differentiator is **the separation of relevance selection from factual
permission**: matching a job term does not create candidate evidence. Projects,
employment, Basic knowledge and learning must retain their scopes.

## Prioritized plan and disposition

| Priority | Finding | Action |
|---|---|---|
| P0 | Value proposition and trial path buried in lengthy technical prose | Rewritten README with early links, authentic hero, three steps and concise features |
| P0 | Setup needs manual secrets and production-oriented defaults | Standard-library initializer for a fresh checkout, mock AI, synthetic profile, independent secrets and persisted fallback-off setting |
| P0 | Video cannot substantiate completed export | Preserve visible limitation; separate renderer previews, deterministic validator example and manual E2E acceptance scenario |
| P0 | Presentation cleanup could erase engineering content | Preserve entire former README in `REFERENCE.md`; leave K3s architecture/docs/configuration unchanged |
| P1 | Navigation is organized around features/operations, not visitor intent | Intent-based docs entry points; fix walkthrough anchor and contributor Docker/local-data guidance |
| P1 | Discoverability is broad/generic | Proposed description, 15 focused topics, owner instructions and social-preview specification; no remote settings changes |
| P1 | No first release returned by API | Candidate version proposal, gated readiness checklist and explicit warning that merge/push to main triggers CD |
| P2 | Community files already cover reproducibility/privacy/a11y | Keep SECURITY, issue/PR forms and code of conduct; add only useful onboarding links, scoped issue proposals and unpublished launch drafts |

## Changes and benefits

- **README:** answers what/why/see/try/license/privacy/install promptly. K3s is
  visible in badges, technology stack, architecture and deployment. Dependency
  markers remain compatible with the existing read-only synchronization check.
- **`REFERENCE.md`:** preserves prior technical content and relative links at the
  repository root. Its banner directs readers to current source defaults and the
  new Quick Start; stale model names, local environment setup and absolute-sounding
  factual/privacy claims are corrected without removing the technical explanations.
- **`docs/quickstart.md`:** prerequisites, synthetic scenario, provider/fallback
  distinctions, platform limitations, troubleshooting and safe shutdown. No
  unmeasured five-minute claim or anonymous public demo shortcut.
- **`scripts/init_demo.py` + tests:** no new runtime dependency, no application/API
  change. Refuses existing configuration, any non-example data entry and a
  symlinked data directory; creates local files exclusively with private modes.
  It never converts or overwrites a production account.
- **Hero WebP:** approximately 97 KiB versus the existing 242 KiB overview PNG;
  removes empty/navigation space, retains the same report and links to the full
  capture. Original images/videos remain unchanged. Provenance/reproduction is
  in [media notes](media/README.md). Existing mobile and template assets are reused.
- **Documentation navigation/contributor links:** readers reach setup and detailed
  evidence without scrolling through every implementation detail. Direct local
  development explicitly overrides the container-only `/app/data` path.
- **[Community launch kit](community-launch.md):** exact owner actions, release
  gates, prioritized follow-up work, three contribution proposals and separate
  LinkedIn/technical-community drafts. No issues, release or promotional posts
  were published; existing community templates were already useful.

## Validation

Checks used fictional data and an isolated Python 3.14 environment; no owner
`.env` or candidate directory was loaded. Existing local dependency drift was
detected, so a fresh environment was installed from the unchanged pinned
requirements before the final run.

| Check | Result |
|---|---|
| `python scripts/check_environment.py --dev` and `python -m pip check` | Passed in the fresh pinned environment |
| `ruff check .` | Passed |
| `python scripts/sync_readme.py --check` | Passed; generated sections still match the existing generator |
| Focused regression command below | **122 passed in 394.88 s** |
| Final `pytest -q tests/test_init_demo.py` recheck after strengthening the no-secret-output assertion | **15 passed in 31.34 s**; overlaps the regression set, not 15 additional distinct tests |
| Local Markdown/HTML links, images and heading anchors in nine changed/new documents | **224 checked; all passed** |
| Six badge URLs, workflow page and issue/security form destinations | HTTP 200; forms redirect to login, so this does not prove private-reporting configuration |
| Existing WebM files loaded with Chromium | Metadata readable: 130.4 s and 39.2 s, both 1152 × 800; sampled report/history footage remains consistent with partial-demo notes |
| Fresh initializer + `docker compose config --quiet` | Passed without starting services |
| Diff/whitespace, changed-file scope and private-key/token-pattern checks | Passed; infrastructure and application implementation files unchanged |

```bash
pytest -q tests/test_init_demo.py tests/test_sync_readme.py \
  tests/test_fact_validator.py tests/test_fact_retrieval.py \
  tests/test_recording_demo.py tests/test_html_resume_access.py \
  tests/test_manual_truth_lock.py tests/test_resume_export_quality.py
```

The first broad invocation hit the shell's 120-second timeout before completing;
it is not counted as a passing run. The completed rerun used no outer shell time
limit and produced the 122-test result above. Pytest-asyncio emitted its existing
unset fixture-loop-scope deprecation warning; no configuration was changed to
silence it. This is not a full-suite or CI-green claim.

### Environment and execution limits

- Fresh initializer output passed `docker compose config --quiet` using a
  temporary project directory and temporary `.env`, without starting containers.
- Port 8000 is occupied by another service on this host. The default Compose
  stack was **not launched**, rebuilt or stopped, and its fixed ports/container
  name were not changed. A clean Linux-host Docker build/start/time-to-login
  remains a release gate. No under-five-minute claim is made.
- No new LLM inference, model download, Gemini call, K3s operation, production
  export, workflow dispatch or deployment was performed. UI-based end-to-end
  successful export/opening remains unverified in this task.
- Focused regressions do not substitute for a complete suite, new CI run or a
  live security/a11y audit. Existing videos remain partial demonstrations.

## Remaining owner decisions

Review the [release checklist, roadmap and proposed GitHub settings](community-launch.md).
Approve any remote metadata/social-preview update or release separately. Do not
merge automatically: `main` has production CD. A safe public demo should be a
separate disposable installation with its own credentials, account storage,
processing isolation, quotas and reset/abuse policy—not the owner's production
instance exposed anonymously. This task does not implement that service.
