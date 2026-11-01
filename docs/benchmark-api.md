# Analysis benchmark API (stage one)

The application uses **REST over HTTP/JSON in FastAPI, with OpenAPI**. This PR
implements the benchmark resource, not the entire integration API. See
[the API migration plan](rest-api-audit-plan.md) for the separate n8n phase.

## Authentication and safety

Use an authenticated owner **session cookie** and `X-CSRF-Token` from that same
session. This is not a public API and does not yet support personal access tokens.
Resource-intensive benchmarks are disabled for the demo account. Existing request
size, origin, account-isolation, rate, disk and AI-call budgets still apply.
URL extraction uses the existing DNS/IP-pinned SSRF-safe importer and browser
sandbox; a URL is never passed to an unrestricted HTTP client.

## Create a run

`POST /api/v1/benchmarks`

Required headers: `Content-Type: application/json`, `X-CSRF-Token`, and an
`Idempotency-Key` of 8–128 ASCII letters/digits/`._:-` characters.

```json
{
  "urls": [
    "https://justjoin.it/job-offer/cloudatus-infrastructure-administrator-katowice-admin-b93a9c40",
    "https://justjoin.it/job-offer/cgi-application-operations-l2-engineering-24-7-warszawa-support-de0bf29c",
    "https://justjoin.it/job-offer/best-s-a--infrastructure-administrator--bialystok-admin"
  ],
  "ollama_model": "gemma4:12b-it-q4_K_M",
  "context": 65536,
  "max_model_calls": 24,
  "recovery_calls": 1,
  "case_timeout_seconds": 90,
  "confirm_costs": true
}
```

Only 1–3 distinct HTTP(S) URLs without embedded credentials are accepted. Model
selection must identify an already available Ollama model; it never pulls models.
The context must be supported by that model. Call attempts are bounded to 1–48;
repair calls to 0–4 per variant; individual wall deadlines to 30–120 seconds.
Admission rejects paired deadlines that cannot fit the account's task budget.

A new request returns **202**, `Location`, `Retry-After: 3`, and:

```json
{
  "task_id": "0123456789abcdef0123456789abcdef",
  "status": "queued",
  "stage": "Waiting in queue...",
  "status_url": "/api/v1/benchmarks/0123456789abcdef0123456789abcdef",
  "view_url": "/tasks/0123456789abcdef0123456789abcdef/view",
  "report": null,
  "error": null
}
```

Reusing the same idempotency key and body returns the existing run, including
after completion (200). Reusing a key with a different body is **409**, not another
paid attempt. Use a new key for a new experiment. Invalid requests are 422,
unauthenticated calls 401, invalid CSRF/demo use 403, and a full queue/rate limit 429.

## Status and results

`GET /api/v1/benchmarks/{task_id}` returns the same envelope. Poll `status_url`,
stopping at `completed`, `failed`, or `rejected`. Responses are `no-store` and
account-local; other accounts and non-benchmark IDs return 404. Partial reports
are saved after each variant, including before an outer timeout.

`completed` means the experiment finished, **not** that every analysis passed.
Inspect each variant's `status`, `is_reliable`, missing source qualifications and
validation issues. A failed or incomplete case is not an optimization success.

Each full/cleaned pair uses a frozen profile/skills snapshot and the same model,
context and repair limit. No CV export or saved job/profile modification occurs.
The cleaner is an experimental projection: it retains qualifications, duties,
unknown content, work conditions and suspicious requirement-bearing benefit text;
it only drops clearly classified, non-qualification context. It also separates
inline bullets. The original source and its fingerprint are retained in the
experiment's metadata, not overwritten.

Provider-reported `input_tokens`/`output_tokens` include repairs. Missing usage is
`null`, not an invented estimate. `input_composition_totals` are **characters and
bytes**, not per-field token counts. `schema_bytes` are transport/grammar bytes,
not a proven share of prompt tokens. Nominal prompt counts can include cached
prefixes; inspect prompt-evaluation and wall times separately.

Runs use the normal account FIFO and appear in Diagnostics → Current background
queue. Pause stops *new* starts, not the active call. Reject affects only waiting
tasks and preserves the record. A retry is a new attempt; deletion is explicit.

The analysis page also submits PDF/DOCX export to this FIFO (`background_export`
on the form), then redirects immediately to a refresh-safe GET status page.
Repeated submission of the same confirmed draft/layout reuses the export task.
The synchronous form contract remains available for existing non-UI clients;
session, origin, CSRF and summary-confirmation checks apply to both paths.

OpenAPI: authenticated `/openapi.json` and `/docs`. Integration-token management,
full resource coverage and a reusable n8n workflow belong to stage two.
