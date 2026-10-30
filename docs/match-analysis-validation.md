# Match analysis validation v2

## Indexed provider contract follow-up (2026-10-29)

A live test using the reported public job and a synthetic profile showed why the
first hotfix was insufficient: the free-form Gemini contract returned no context
or responsibilities. Validation therefore fell back to inherited parser sections.
The next validation then treated those derived sections as model classifications.
Synthetic complete-model fixtures had not exercised that failure.

Both providers now receive indexed source passages without parser category hints.
Gemini returns a primitive, API-compatible rows schema; missing IDs trigger bounded
recovery of only those IDs. Code restores exact quotes from the inventory, checks
coverage and validates fact references independently. Ollama's initial request now
uses the same keyed schema and matching keyed-response instructions as recovery.
Competencies derived from a duty can coexist with the duty during revalidation;
this is not a conflicting employer qualification. No heading-name aliases are used.

Live Gemini with a synthetic profile classified the full source as 9 mandatory,
5 preferred qualifications and 7 duties, and remained reliable on revalidation.
No private profile was exported for this test. The NFJ entrypoint-host alias maps
only that exact hostname to the canonical public site, preserving the offer path,
query and existing URL security checks.

## Semantic source classification (2026-10-29)

For provider responses with explicit context/responsibility dispositions, literal
model classifications now replace inherited parser categories. Every nonempty
source line must be covered by a verifiable source quote; invented quotations,
conflicting categories and omitted passages keep the result incomplete. Explicit
candidate-condition wording cannot disappear into context. Candidate evidence,
proficiency, tenure, negation and AND/OR checks still run independently.

The section dictionary remains a hint and a legacy source-review mechanism. It
cannot veto a complete model interpretation because an unfamiliar heading inherited
a preceding duty/benefit category. No Cloudfide heading aliases or Spark/PySpark
slash exception are needed. Slash meaning comes from the model's explicit operator
and uncertainty, with factual support checked separately.

Ollama sees the complete offer alongside each batch of indexed passages. Its response
grammar no longer fixes categories from inherited section hints; each indexed
passage still needs a disposition. Gemini is instructed to quote and classify every
source line, including headings. Sparse older responses retain the legacy review
path rather than claiming full semantic coverage.

Regression coverage includes unfamiliar headings, 24 section permutations, plain,
Markdown and bulleted formats, quotation/coverage failures, and both provider
contracts. These are synthetic model responses, not a live model-quality benchmark.
Saved reports require reanalysis after deployment.

## SaaS section boundary regression

The supplied LanceSoft report showed technical and professional requirements as
responsibilities. A synthetic reconstruction using the supplied passages confirms
that `Required Technical Skills` and `Professional Requirements` inherited the
preceding responsibility category. These headings now start mandatory sections;
`ATS Keywords` starts a separate, preserved context category. Keyword lists cannot
be promoted to qualifications by model output. Coverage also normalizes formatted
headings before checking for omitted requirement passages.

Regression tests cover plain and bold headings, all 15 listed qualifications,
responsibility separation, and rejection of a model qualification sourced only
from the keyword list. The original saved LanceSoft generation is unavailable in
this workspace. This change does not rewrite saved analyses: they need a new
analysis after deployment, with unresolved passages and evidence still validated.

The Netige / CodeARM incident was reconstructed with synthetic Polish and English text in `tests/test_match_report_integrity.py`. The original posting and raw model response were not available. No provider-specific cause is asserted.

## Causes and changes

- The section parser recognized “co oferujemy”, but not “Oferujemy:”. Content inherited the preceding preferred qualification category. Presentation markers could also prevent recognition. A shared line normalizer now handles headings, bullets, numbering and bold markup; both source parsing and compact Ollama inventories use it.
- Application encouragement is context even when it occurs inside a qualification section. Work arrangements and client visits are employment context requiring personal confirmation, outside qualification scoring. Section titles remain in `source_sections`. Organization and benefits remain source context. Explicit qualification wording in an unusual/context section is retained with uncertain priority for review.
- Scoped support evidence previously depended on support-related English wording. Documented Windows/Microsoft 365 user incident resolution and Polish diagnosis duties now support general IT support. Title/technology metadata are excluded from these activity matches. The semantic validator also reruns this scoped retrieval when the model reports missing evidence. Titles alone still prove neither competence nor tenure.
- Short named compound lists now produce independently assessed components. M365 / Microsoft 365 / Office 365 evidence is product-specific; on-premises AD does not establish Entra ID, and M365 does not establish Intune. Source AND/OR takes precedence over model output. Recognized example lists use alternatives; mixed logic stays ambiguous for review. Existing semantic scope, proficiency and tenure checks remain in force.
- Coverage is separate from `classification_issues` and `evidence_issues`. Rejected model qualification/context classifications, removed invalid citations, unsupported confirmations and unresolved interpretations block an unconditional reliable result. They cannot boost the score. Absence of a fact remains “not confirmed”, never a confirmed inability.
- The report no longer claims that fallback completeness guarantees correctness. All providers use `AnalysisValidator`; the rules apply equally to Gemini, Ollama and source review/fallback.

## Synthetic before / after

| Passage | Before reconstruction | After |
|---|---|---|
| Experience in IT support | Missing despite Windows/M365 user incident duties | Confirmed from activity facts; missing with title-only profile |
| Oferujemy → training budget / tools | Preferred qualifications, reported missing | Benefits context, excluded from scoring |
| Remote/hybrid work and client visits | Unconfirmed qualification | Employment context for personal confirmation |
| Knowledge of M365 + Entra ID + Intune | One partial row without item results | AND: M365 confirmed; Entra ID and Intune not confirmed; overall partial |
| M365 or Entra ID or Intune | Combined scope | OR: individual results shown; a confirmed branch suffices |
| Model labels training budget as qualification | Could pass completeness | Row excluded, classification issue recorded, review required |

No expected HIGH result is embedded in fixtures or scoring.

## Existing reports

New analyses have `validation_version = 2`; older serialized analyses default to zero. The report template requests reanalysis for older validation versions. Loading a report does not recompute or overwrite its analysis or CV. Reanalyze the original saved job against the current verified profile to create a new result; historical evidence may have changed.

Read-only inspection on 2026-10-23 found 68 local `data/generated/*/analysis.json` paths: 67 readable reports using older rules and one unreadable file. None of the readable company fields identified Netige or CodeARM. The counts are local inspection results, not a migration inventory committed as personal report data. No saved report, profile or CV was modified.

## Files

- `app/services/job_sections.py`: section boundaries, formatted headings, context and uncertain qualification passages.
- `app/services/ollama_analysis.py`: shared source normalization for compact inventories.
- `app/services/evidence_matching.py`: support activities and independent Microsoft product scopes.
- `app/services/semantic_requirements.py`: model-output normalization, source list logic, component evidence and validation issues.
- `app/services/grounded_requirements.py`: fallback components, scoring inputs and separate reliability gates.
- `app/services/analysis_validator.py`, `app/models/job.py`: validation diagnostics and historical version defaults.
- `app/services/ollama_provider.py`: preserve classification/evidence reasons in final validation errors.
- `templates/analysis.html`: qualified fallback message, diagnostics and historical report reanalysis notice. Component status rendering already existed; normalized components now reach it.
- `tests/test_match_report_integrity.py`: synthetic regressions and rendered report checks.
- `tests/test_llm_first_analysis.py`, `tests/test_provider_fallback.py`: update expectations so coverage cannot hide ambiguity or invented evidence.

The working tree contained unrelated changes before this fix; those were preserved.

## Verification in this workspace

Final focused run: **256 passed**, including **36 new regression cases**, with one existing Starlette/httpx deprecation warning. It covers matching, source sections, semantic/fallback analysis, Microsoft component scopes, Truth Lock, both provider adapters, compact responses, fallback recovery and report rendering. All provider calls use synthetic data and mocked transports; no paid API was called.

Passed: `ruff check .`, `git diff --check`, `python -m pip check`, and `python scripts/sync_readme.py --check` (900 collected tests).

The full suite was invoked serially and then in four groups, but did not complete successfully. Native PDF processing exceeded time limits (including `test_ats_preserves_long_text_and_reading_order` and pagination processing); browser security cases `popup` and `blank-popup` failed with `Browser processing exceeded its deadline`. The grouped run was interrupted rather than presented as a full pass. These checks need a clean rerun in the pinned CI environment. No unrelated exporter/browser code was changed to silence these failures.

`python scripts/check_environment.py --dev` also reports existing installed-version drift:

| Package | Required | Installed |
|---|---|---|
| fastapi | 0.143.2 | 0.143.0 |
| pydantic-settings | 2.16.0 | 2.15.0 |
| playwright | 1.64.0 | 1.63.0 |
| ruff | 0.17.1 | 0.17.0 |
