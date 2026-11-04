# Batch API security review — 2026-11-03

## Scope and evidence

Code review of `/api/v1/batches`, JSON/TXT input, account routing, the shared
authentication/CSRF/body boundary, URL extraction, task admission/retries,
provider selection, draft export, quotas and result links. Regression tests use
synthetic profiles and mocked providers; URL-guard tests exercise the real
extractor without sending requests to private/metadata addresses. No production
login, active attack against `cv.banas.dev`, paid AI call or deployment was made.

The owner supplied a diagnostic snapshot of nine offers: seven `Success`, one
`Review_required` with a real Gemini fallback, one `Error` after both providers
failed. These are observations from that snapshot, **not** an independent live
benchmark. Latency was approximately 96–165 seconds per analysis with 3–7 model
calls; the table does not establish complete PDF/DOCX export latency or CV quality.
Truncated error messages are insufficient to diagnose the two model failures.

`Truth Lock: 0` in this dashboard is a recorded warning count, not a validation
level or an OFF switch. The diagnostic writer defaults this count to zero, so
it alone cannot establish that every claim was verified or that no warning
occurred at a later export stage. Inspect the saved analysis, CV warnings and
export review. In particular, a very small requirement count should be reviewed
against the actual posting rather than interpreted as proof of completeness.

## Findings and changes

### BATCH-01 — implicit cross-provider fallback (medium, privacy)

Before this change, `llm_provider: ollama` inherited the account-wide fallback
setting. An Ollama failure could transmit job/candidate facts to Gemini without
an explicit choice on that individual batch. This was documented routing, not
an unauthenticated breach, but is an unsafe surprise for local-only automation.

**Fix:** strict JSON boolean `allow_fallback`, default **false**. The request
policy is copied into each child and applied to a request-local router. `true`
only permits fallback when global settings also allow it; it cannot enable an
owner-disabled fallback. Explicitly selecting Gemini as primary still uses the
cloud. Existing manual UI jobs keep their normal global policy. Legacy batch
children identified by their internal key default to no fallback, including UI
retries. Old parent payload defaults are normalized during idempotency lookup
so upgrading does not encourage a paid rerun under a new key.

### BATCH-02 — incomplete saved exports (medium, integrity/availability)

Previously, application metadata was saved before PDF/DOCX generation. A failure
or cancellation could leave a partially generated CV in History, linking its
draft to an incomplete export. Existing download/summary checks were still
present; this finding is not a demonstrated authentication or Truth Lock bypass.

**Fix:** render both artifacts and application metadata inside a private temporary
directory on the same filesystem. Validate exports there, reserve a unique final
name without overwriting an existing CV, bind any summary confirmation to that
final slug, and publish the directory with one rename. Handled render, metadata,
publication and cancellation failures clean up staging/reservations and retain
the original draft. Regression tests also verify that repeated exports do not
overwrite earlier documents.

### BATCH-03 — stale export quota admission (low, resource protection)

The original HTTP request/per-offer check could precede expensive rendering.
Storage could change while work waited or exports could themselves exhaust quota.

**Fix:** recheck disk/file-count quotas at export start, after rendering, and
before publication, including staged output in the accounting. A failed quota
check prevents publication; it does not delete an existing CV to make room.

## Boundaries checked and retained

- Protected API requests require a valid server-revocable session. No bearer
  token, anonymous ingestion, new CORS exception or public artifact route added.
- Mutation tokens are compared to both the cookie and current signed session;
  a valid old-session token cannot be replayed simply by matching its cookie.
  Foreign-origin requests remain rejected. Demo submissions remain disabled.
- Task IDs are validated before filesystem access. Private/demo result lookups
  remain in their authenticated runtime, regardless of query/header account hints.
- JSON options reject unknown fields; TXT filename is not used as a storage path.
  HTTP bodies, TXT bytes, URL count (before deduplication), URL length, model names
  and context selections are bounded. Fallback permission is not string-coerced.
- URL fetches retain the existing public-IP/DNS-pinning/redirect and guarded
  browser boundary. Non-HTTP URLs and URL credentials/fragments are rejected;
  local/private/metadata destinations do not reach transport.
- Idempotency remains account-local and serialized across processes; changed
  consent/options conflict rather than silently starting additional paid work.
- Per-offer deadlines, queue limits, persistent daily model-call budgets,
  Truth Lock and exact-summary confirmation remain active. Batch completion is
  distinct from successful completion of every offer.

## Validation and limitations

Targeted tests: `test_batch_fallback_policy.py`, `test_batch_security_audit.py`,
`test_draft_export_transaction.py`, the existing batch model/API/security tests,
task/queue tests, extractor/browser security tests and summary-confirmation tests.
The macOS guide's extracted login function was exercised under **zsh 5.9** against
a synthetic local HTTP server for success, denied GET, denied POST and missing
CSRF. This verified URL-encoded credentials, cookie rotation, hidden password
input and failure cleanup. Shell/JSON examples and local Markdown links were
also checked. This is not an actual macOS or production-server login test.

This is a focused engineering review, not a certification or a guarantee of no
vulnerabilities. Important residual constraints:

- Private, single-owner self-hosting remains the threat model, not public
  multi-tenant SaaS. An authenticated owner can intentionally consume resources
  within the configured limits.
- Account semaphores are in-process; this work does not establish globally shared
  concurrency guarantees for arbitrary multi-worker deployments. Disk checks are
  bounded admission checks, not filesystem-level hard quotas.
- Handled failures are covered; power loss or `SIGKILL` can still leave private
  staging directories/empty reservations. There is no new crash-recovery janitor,
  and this patch does not claim fsync-level durability or encryption at rest.
- Prompt injection and imperfect extraction/model interpretation are not
  eliminated. Human review remains required; no applications are submitted.
- Existing saved documents are not retroactively deleted or repaired. The new
  routing/export behavior takes effect only after deploying this code; no
  production settings were changed by this review.

## Operation and rollout

Use [the macOS/zsh guide](../batch-api-macos-pl.md) and
[the API contract](../batch-api.md). Until the change is deployed, turn off global
fallback in the UI if only local Gemma processing is acceptable. After deployment,
leave `allow_fallback` false or omit it. Opt-in cloud fallback requires both the
explicit boolean and the global setting. No new dependency, database migration
or environment variable is required. Keep completed documents/drafts; do not
resubmit all successful offers merely to retry the failed ones.
