# REST/FastAPI/OpenAPI audit and migration plan

## Scope and decisions

Stage one: repair factual analysis, expose current FIFO/controls, add a bounded
multi-offer benchmark and measure token composition. Stage two (separate PR,
after review): a complete `/api/v1` integration API for n8n. Keep FastAPI;
OpenAPI documents the contract. xAPI/Experience API is not applicable.

Do not publish the private profile, candidate evidence, credentials, cookies,
prompts or full benchmark reports in Git. Publish only sanitized measurements.

## Findings verified in code and live validation

1. Completed provider calls are not proof of a valid analysis. Empty JSON fields,
   false context coverage, unweighted qualification tags and unsupported evidence
   previously reached inconsistent paths. Enforce bounded structural repair and
   independently check source dispositions and evidence before scoring.
2. Qualification coverage is not merely "every source line appeared somewhere".
   Explicit prerequisites cannot be hidden as context or portal competencies.
   Preserve duties separately and keep optional conditions out of mandatory scoring.
3. Portal levels (`regular`, `B2`) are metadata. Revalidation must be idempotent;
   losing a supporting quote must not introduce a new mandatory requirement.
4. A model's invented minimum tenure must never become an employer requirement.
   Bind tenure to original source wording, not the candidate's years of experience.
5. Compound language conditions require their own levels: Polish C1 is not an
   English C1 requirement when the source explicitly says English B2.
6. The input is repeated across batches/repairs and includes candidate evidence,
   instructions and the source offer. Removing benefits alone is not guaranteed
   to reduce the dominant cost. Measure provider counts and input composition.
7. Global polling must not refresh stale cookies or follow redirects to `/login`:
   an old tab could otherwise overwrite/revoke a newly switched account session.
8. Browser import needs bounded bootstrap as well as navigation time. Prefer the
   matching installed headless shell under the same kernel/network restrictions;
   never select another browser revision or relax SSRF/network policy for tests.
9. Copied inline headings/bullets must be segmented before normal analysis, not
   just in the experimental cleaner. Otherwise one context row can hide many
   qualifications. Keep the original source untouched for provenance.
10. Repeated portal proficiency labels such as `regular` are parser-owned
    metadata. Canonicalize only those standalone supporting spans; contradictory
    model dispositions must not turn them into scored conditions or block an
    otherwise valid analysis. Explicit language requirements remain assessable.
11. A synchronous export exceeded the public proxy/browser deadline while still
    finishing PDF and DOCX on the server. Refresh then replayed its POST and was
    rejected by the origin boundary. Browser exports now use FIFO admission and
    a GET status redirect, without weakening origin/CSRF/confirmation checks.

See [the exploratory measured results](benchmark-results-stage-one.md): the
first actual model experiment is not evidence that cleaning saves tokens safely.

## Current UI/function inventory → proposed v1 resources

The source inventory has 67 routes in `web.py`, 8 in `custom_cvs.py`, and the two
new benchmark routes. This is not a claim that all 77 are a finished public API.

| Area | Existing functionality | Proposed stage-two resources |
|---|---|---|
| Import | URL extraction, pasted-text cleanup | `/offers/imports`, `/offers/{id}` |
| Workflow | analyze, reuse saved analysis, compare | `/analyses`, `/analyses/{id}/tailorings`, `/comparisons` |
| Jobs | status/view, retry, queue controls | `/tasks`, `/tasks/{id}`, `/tasks/{id}/attempts`, `/queue` |
| Analysis | source/evidence questions, saved report | `/analyses/{id}`, `/analyses/{id}/evidence` |
| CV | generation, preview, manual edit/reset, versions | `/cvs`, `/cvs/{id}`, `/cvs/{id}/versions` |
| Export | PDF/DOCX, layout, photo use/hide, download | `/exports`, `/exports/{id}`, `/artifacts/{id}` |
| Truth boundary | Truth Lock, summary review/confirmation | `/cvs/{id}/reviews`, `/cvs/{id}/confirmations` |
| Custom CV | import, propose changes, apply/reject, preview/export | `/custom-cvs`, `/custom-cvs/{id}/proposals` |
| History | saved reports/CVs, explicit deletion | paginated resource lists and explicit `DELETE` |
| Profile | contact, interests, photo | `/profile`, `/profile/interests`, `/profile/photo` |
| Skills | CRUD, enable/disable, attested evidence | `/skills`, `/skills/{id}/evidence` |
| References | upload/remove reference CVs | `/references` with constrained multipart upload |
| Providers | health, fallback/model choices | `/providers`, `/settings` |
| Diagnostics | run log, clear log, live queue | `/diagnostics/runs`, `/queue` |
| Benchmark | paired analysis experiment | `/benchmarks` (stage one implemented) |
| Account | sessions/password, integration-token lifecycle | `/sessions`, `/tokens`; no secrets in read responses |

## Proposed implementation order

### P0 — shared application services and contract

Extract command/query services from request-bound UI handlers. Both HTML routes
and JSON routes invoke the same services; do not scrape HTML or synthesize a
privileged Request to bypass guard/CSRF/confirmation. Define Pydantic request,
response, pagination and error schemas before adding resource routes.

Acceptance: parity tests for UI vs JSON results, explicit enum/status meanings,
schema examples validated against OpenAPI, no undocumented browser-only input.

### P1 — machine authentication and resource isolation

Add revocable, expiring, hashed personal access tokens with narrowly scoped
read/write/AI/export permissions. Show a token once, redact it from logs, never
reuse provider keys or worker secrets. Cookie-authenticated writes retain CSRF;
bearer-only requests are separate and cannot borrow a browser's account claim.
Token-to-account binding must be verified server-side before runtime selection.

Acceptance: owner/demo/cross-account matrix, expired/revoked/wrong-scope tests,
cookie/bearer confusion tests, existing origin/body/rate/disk limits unchanged.

### P2 — asynchronous core workflow

Offer import → analysis → tailoring → explicit summary confirmation → export →
artifact download. Use 202 + Location/status URLs; stable idempotency with 409 on
key/body conflict; revision checks for edits; serial account task admission.
Default to n8n polling rather than arbitrary callback URLs/webhook SSRF exposure.

Acceptance: replayed n8n requests do not duplicate charges or overwrite edits;
restart/retry does not falsely imply successful processing; incomplete analysis
never produces HIGH/APPLY; exports retain Truth Lock and human confirmation.

### P3 — remaining resources and n8n templates

Profile/skills/evidence/references/custom CVs/history/settings/diagnostics follow
the same service and permission model. Publish a credential-free n8n example
with separate read/write credentials, polling, bounded backoff and explicit error
branches. Never commit a live session cookie, PAT or private CV.

## Measurement/optimization gates

1. Use BEST, CLOUDATUS and CGI; executor/junior inference must be finished before
   measurement. Wait for active account work instead of terminating it.
2. Full vs conservative cleaned input, same frozen profile/model/context/repair
   budget, analysis only. Record failures and omitted prerequisites, not only speed.
3. Record actual provider tokens, prompt/evaluation/load/wall times, call counts,
   composition characters/bytes and cleanup provenance. Do not call schema bytes
   token counts or treat cache hits as zero nominal input.
4. First optimize the measured bottleneck: repeated evidence/prompt payload,
   batching/repair, or safe source projection. Do not remove whole headings blindly.
5. Keep cleaning opt-in/benchmark-only until coverage and factuality remain valid.
   One sequential pair is exploratory, not a statistically significant latency
   study; later randomize/ABBA order and include cold/warm-cache observations.

## Release/rollback

Full test suite plus browser/account isolation, SSRF, API/idempotency/CSRF,
queue pause/reject/retention and export tests must pass before release. Preserve
the pre-existing Modern Sidebar commit in a separate dependency PR; no unrelated
user changes are dropped. Publish the feature PR against that branch, without
automatic merge. Drain active work, deploy an exact tested image, verify health
and account isolation, retain previous image references for rollback.

No "reset server/model" button. Pause only stops new starts; rejection applies
to queued tasks; records survive until explicit deletion. Deploying with a paused
nonempty queue requires deliberate resume/rejection, not silently running it.
