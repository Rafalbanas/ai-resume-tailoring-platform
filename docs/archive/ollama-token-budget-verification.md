# Ollama token budgeting and evidence verification — 2026-10-12

## Measured failure and its cause

The failing saved offer is Motorola Solutions Systems Polska / Software Engineer (DevOps), source hash `8016f0fbc6ab5ce2ebe873ae8e2743294f7ddd587a0110db8a839418efce32cd`, 3,423 characters. The saved Gemini fallback report contains 22 qualification rows (8 mandatory, 14 preferred). Other Motorola DevOps offers exist locally; this source was selected by its stored output-limit fallback reason, not just its title.

Existing Docker logs record two complete HTTP responses from Ollama:

| Original Ollama call | Prompt tokens | Generated tokens | Provider duration |
|---|---:|---:|---:|
| Initial attempt | 17,429 | 8,192 | 185.257 s |
| Whole-report retry | 17,429 | 14,827 | 489.403 s |
| Total | 34,858 | 23,019 | 674.660 s |

The retry budget was `32768 - 17429 - 512 = 14827`, constrained by the configured context. Both responses hit their exact generation ceilings. Code handled `done_reason=length` before JSON validation, retried the whole request once, then raised the reported output-limit error. There is no evidence of an early streaming cancellation: the client uses `stream=false`. The stored workflow diagnostic is 699.408 s including fallback work; separate Gemini call token counts are not available and are not inferred.

The old `JobInterpretation` repeated requirement names, full quotes, full explanations, component explanations, context and role text, with unbounded arrays/strings. Input repeated facts in the candidate summary, source catalogue and skills evidence, and repeated job passages in section hints. This made both input and generated output unnecessarily large. The original raw failed response was not retained in the normal task run, so the exact generated repetitions cannot be reconstructed as fact.

Observed environment: Ollama 0.40.1, `qwen3.5:9b`, Qwen35 9.0B Q4_K_M, model context metadata 262,144. Deployment context remains 32,768; loaded allocation also reported 32,768. The observed loaded weight/KV allocation was 6,558,444,420 bytes. Model metadata supports boolean thinking (`false`/`true`, default `true`), while the application already explicitly requests `think=false`. New responses contained no thinking field. Separate reasoning-token counts are unavailable; they are recorded as null, not estimated as zero.

Client settings are unchanged: output ceiling 8,192; context 32,768; temperature 0; keep-alive 15m; concurrency 1; connect timeout 10 s; read timeout 540 s. Model defaults include presence penalty 1.5, top-k 20 and top-p 0.95. No GPU settings, model selection, deployment environment or default provider were changed. No production deployment or merge is part of this PR.

The distinction between context, generation controls, final-response fields and model-specific thinking controls was checked against the official [Chat API](https://docs.ollama.com/api/chat), [thinking documentation](https://docs.ollama.com/capabilities/thinking), and [context documentation](https://docs.ollama.com/context-length).

## Implementation

- An Ollama-only compact contract returns short passage/evidence references, bounded capability labels, one concise explanation, and independently referenced AND/OR components. The public `JobAnalysis` contract and Gemini analysis contract remain compatible; full original quotes/facts are reconstructed in code.
- Full job source, including unfamiliar headings, context and duties, stays available to the model. Candidate evidence is indexed once; owner metadata and employment dates are deduplicated. No contact/profile object is unnecessarily repeated.
- Output budgeting and context reservation are separate. A conservative UTF-8 planning heuristic is explicitly an estimate, never an API token measurement. Batches preserve global source IDs; the complete evidence catalogue is retained in each batch. If even one passage plus the evidence cannot fit, a context-budget error is raised rather than silently dropping candidate facts or job text.
- Simple and medium synthetic offers use one analysis call. A 48-requirement fixture uses two bounded batches with the same 8,192 output / 32,768 context limits. A larger output limit is not the default recovery strategy.
- Only fully closed and schema-valid row objects from a length-truncated JSON array can be salvaged. The truncated report itself is never accepted. Missing passages receive targeted recovery; successful passages are not regenerated. By default at most four extra recovery calls are allowed for the entire analysis (`OLLAMA_ANALYSIS_RECOVERY_CALLS`, range 0–8), including subdivision and repairs requested by final coverage validation. Completed passages remain intact. The shared operation timeout still applies. If source passages remain unresolved, Gemini analyzes only those passages and the combined interpretation is validated against the full original source. There is no unbounded whole-report retry or budget doubling.
- Known qualification/candidate passages cannot silently disappear as context-only rows. Unfamiliar experience and soft-skills headings are checked. Targeted recovery uses a flat assessment schema and explicit instructions. Literal tenure/language conditions cannot become unweighted portal tags; category correction does not invent evidence or promote a match status.
- Expansion retains independent AND/OR evidence, proficiency and tenure. Identical repeated source/assessment rows are merged; conflicting duplicates fail explicitly. Existing source/fact/Truth Lock validation remains active. Unknown candidate capabilities returned as role evidence survive validation instead of being dropped.
- Distinct error categories cover output limits, context budgets, malformed JSON, schema failures, source coverage, timeouts, unavailable service, HTTP failures and invalid/nonfinal envelopes. Configured Gemini fallback remains in the router, with failed primary telemetry retained.
- Per-operation metrics and bounded provider history record provider/model, input/output counts, unavailable reasoning counts, client/provider time, generation settings, termination cause, recovery count and assessed coverage. Successful and failed tasks persist only an allowlisted diagnostic subset; no prompts, raw CVs, evidence text or API keys enter diagnostic logs. Metrics appear in the existing technical view, without changing the main interface.

## Evidence strength and Role Evidence

A workflow file is implementation evidence, not proof of successful execution. CI/CD assessment distinguishes declaration, documented use, implementation and an explicitly attested operational result. Unsupported confirmed results are downgraded to the supported scope with an explanation; explicit documented execution is retained. This applies to both qualification rows and the source of Role Evidence counters. The summary is recomputed from the displayed validated rows.

A read-only GitHub check found recent successful `ci.yml` runs for this repository. Those runs are independent evidence; they do not make an old profile sentence saying only that a workflow file exists into an execution attestation. Private facts and skill records were not rewritten automatically. Operational-result assessment trusts explicit supplied factual attestations and is not a live verification of every external project.

## Validation and limitations

Targeted coverage includes 5, 22 and 48 requirements, long duties/qualifications, duplicate statements, incomplete profiles, AND/OR components, truncated JSON salvage, missing-source recovery, unfamiliar headings, schema/type/HTTP errors, context limits, diagnostic privacy, CI/CD strength and Role Evidence consistency. Existing provider, comparison, task, content/summary and semantic matching contracts were checked. No Gemini inference was run.

Development exposed a second issue: a short complete JSON response can still omit candidate conditions by labeling them context. Early real trials with insufficient coverage were rejected and are not counted as successful analyses. A focused eight-passage recovery call completed with 7,624 prompt tokens, 919 output tokens and 22.703 s provider duration. Final validated measurements are recorded below after the complete test run.

Source recognition is a coverage aid rather than a claim of perfect language understanding. Unusual ambiguous source or excessive evidence can produce an explicit review/error and configured fallback. Planning estimates are conservative and not tokenizer measurements. Reasoning-token counts depend on API support. Private runtime artifacts remain outside Git.

## Final measured run and completed source review

The final actual Ollama analysis used the same source hash, model and configured limits, with no Gemini client or fallback. The initial response completed below its output limit. Two unassessed source IDs were recovered in bounded, targeted calls, preserving all successful rows.

| Final call | Prompt tokens | Output tokens | Provider duration | Termination |
|---|---:|---:|---:|---|
| Main analysis | 9,136 | 7,106 | 144.589 s | stop |
| Targeted recovery | 7,576 | 511 | 14.963 s | stop |
| Final missing passage | 7,552 | 98 | 6.781 s | stop |
| Total | 24,264 | 7,715 | 166.333 s | No output-limit termination |

Measured analysis wall time, including local initial validation: **170.20 s**. Generated responses were subsequently revalidated and alias duplicates normalized locally, with **zero additional AI calls**. Total actual Ollama tokens were **31,979**, compared with **57,877** for the two old failed Ollama calls alone (Gemini tokens were unavailable). Initial prompt size fell from 17,429 to 9,136 actual tokens. The old whole workflow including fallback took 699.408 s; the comparison does not pretend that Gemini token metrics are available.

Every original saved qualification quote was checked against the normalized report: **22/22 covered**, no omitted original requirements. The complete source review contains **28 unique assessed qualifications: 14 mandatory and 14 preferred**. The six extra qualifications are five soft-skill statements and the explicit hands-on experience condition under the unfamiliar source headings; they were present in the source but absent from the original 22-row report. Portal technology tags remain separate role evidence and do not create mandatory blockers. The result is **LOW / REASONABLE_STRETCH**, with 0 confirmed, 19 partial and 9 not confirmed, and no confirmed absences. No minimum HIGH/MEDIUM score was imposed.

The model also returned alias repetitions (a concise capability title and the original statement for the same source scope). Local normalization merges these when source, priority, tenure, proficiency and substantive scope agree; distinct AND branches and independent API integration/debugging scopes survive. Conflicting duplicate statuses cannot promote a match. The normalized report has zero duplicate scoring rows and its counters sum to its visible 28 assessed rows.

There were six complete local development analysis trials and one focused eight-passage test while diagnosing output, coverage and alias handling. Earlier incomplete semantic results were rejected; they are not silently counted as successes. All were local Ollama calls; **zero Gemini inference calls** were made during this work. Only the final accepted run is used in the before/after table. This is a recorded validation case, not a guarantee that every unknown future offer completes in one call.

Private profile, bank, existing history and global provider configuration were not written by these test scripts. Generated validation artifacts remain in a protected local directory outside the repository. The isolated worktree also leaves the original working directory's pre-existing uncommitted changes untouched.

## Final automated validation

Full suite: **434 passed, 2 skipped**, with 48 deprecation warnings, in 145.40 s. `ruff check app tests` and `git diff --check` both passed.


## Targeted repair follow-up (2026-10-14)

The default now permits four additional Ollama repair calls within the existing operation timeout. Repairs start with a keyed passage contract, retain complete valid objects even when keyed JSON is truncated, and also handle explicitly identified omissions from final semantic coverage validation. After exhaustion, the Gemini fallback receives only unresolved source passages; the combined interpretation is revalidated against the full original offer and candidate facts. This does not turn unconfirmed candidate competence into a confirmed match. Structural source errors still require review.

Validation: full suite **531 passed, 2 skipped**, followed by **60 provider/recovery/token tests passed** after adding keyed truncation recovery (including two additional regressions). Ruff and whitespace checks passed. A read-only replay of the previously incomplete support offer completed with Ollama alone in three calls, including two targeted repairs: **26,329 input + 10,461 output = 36,790 reported tokens**. Source completeness passed; no Gemini inference was used for this replay. This checks completion of source assessment, not independent correctness of every interpretation or a hiring outcome. Existing application records were not overwritten.
