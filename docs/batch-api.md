# Batch CV API

[Polish quickstart (macOS)](./batch-api-macos-pl.md)

The owner-only API processes explicitly selected job URLs **sequentially**, without
discovering/crawling additional offers. It saves ordinary analyses/drafts in
**History** and optionally generates PDF/DOCX using the normal export pipeline.

## Endpoint reference

All endpoints require the existing authenticated session cookie. POST requests
also require the session-bound `X-CSRF-Token` header.

| Method | Endpoint | Purpose | Additional header |
| --- | --- | --- | --- |
| GET | `/api/v1/batches/options` | Discover models, themes and limits | — |
| POST | `/api/v1/batches` | Submit URLs and options as JSON | `Idempotency-Key` |
| POST | `/api/v1/batches/upload` | Submit TXT `file` and JSON `options` as multipart | `Idempotency-Key` |
| GET | `/api/v1/batches/{task_id}` | Read progress and incremental results | — |
| POST | `/api/v1/batches/{task_id}/cancel` | Cancel remaining offers | — |

Cancellation is cooperative: the current offer finishes, remaining offers are
cancelled and saved results are preserved. Inspect `cancellation_requested` and
continue polling until the batch reaches a terminal status. This does not undo
completed exports. Cancelling a running batch returns `202`; otherwise `200`.

The ready-to-run [CLI](../scripts/batch_api.py) supports `options`, `upload`,
`status`, `watch` and `cancel`; see the [Polish instructions](batch-api-macos-pl.md#automatyzacja-skryptem-batch_apipy)
for login, three-file submission, a private JSONL manifest and monitoring.

## Authentication and file submission

Use the existing session cookie and session-bound CSRF token. There are no bearer
tokens or anonymous access. Use HTTPS outside local development. Protect cookie
files: they grant account access. Do not commit cookies, URL lists or generated CVs.

Prepare a UTF-8 TXT file (optional BOM), one URL per line or whitespace-separated.
Maximum: 50 input URLs, 64 KiB. Canonical duplicates are processed once, in order.
The URL bound applies before deduplication; there is no unbounded bulk mode.
Invalid tokens, credentials in URLs and fragments are **rejected**, not stripped.

```sh
BASE=http://127.0.0.1:8000
umask 077
curl -fsS -c cookies.txt "$BASE/login" >/dev/null
CSRF=$(awk '$6 == "csrf_token" {print $7}' cookies.txt | tail -1)
curl -fsS -b cookies.txt -c cookies.txt \
  --data-urlencode "csrf_token=$CSRF" \
  --data-urlencode "username=$CVTAILOR_USERNAME" \
  --data-urlencode "password=$CVTAILOR_PASSWORD" "$BASE/login" >/dev/null
CSRF=$(awk '$6 == "csrf_token" {print $7}' cookies.txt | tail -1)
curl -fsS -b cookies.txt -H "X-CSRF-Token: $CSRF" \
  -H 'Idempotency-Key: my-offers-2026-11-02-v1' \
  -F 'file=@jobs.txt;type=text/plain' \
  -F 'options={"llm_provider":"ollama","ollama_model":"gemma4:12b-it-q4_K_M","template_name":"ats_classic","tailoring_level":0.3}' \
  "$BASE/api/v1/batches/upload"
```

Use your own credentials and an installed Ollama model, not necessarily the
example. `options` is a JSON object without `urls`; unknown fields are rejected.

## JSON submission and options

`POST /api/v1/batches` uses the same headers with `Content-Type: application/json`:

```json
{
  "urls": ["https://justjoin.it/job-offer/example", "https://nofluffjobs.com/pl/job/example"],
  "llm_provider": "ollama",
  "ollama_model": "gemma4:12b-it-q4_K_M",
  "ollama_context": 65536,
  "template_name": "ats_classic",
  "tailoring_level": 0.0,
  "export": true
}
```

- `llm_provider`: `auto` (default), `ollama`, `gemini`, `mock`, configured `n8n`.
- `ollama_model`: installed model name; empty uses the configured default.
- `ollama_context`: 32768, 65536 (default), 98304, 131072.
- `gemini_model`: optional model identifier (letters, numbers, dots, underscores,
  dashes; maximum 100 characters), default is the configured Gemini model. Applies
  to Gemini primary/fallback without changing other tasks or global settings.
- `template_name`: `ats_classic` (default), `modern_sidebar`.
- `tailoring_level`: 0–1, with the same meaning as the UI.
- `export`: true (default) generates PDF/DOCX; false saves analyses/drafts only.
- `allow_fallback`: strict JSON boolean, **false by default**. With `ollama`, a local
  failure will not silently send candidate/job data to Gemini. Explicit `true`
  permits the existing fallback chain only if the global fallback setting also
  allows it; it cannot override an owner's global disable. The policy is retained
  with each child task/retry without changing the shared router or other tasks.

`GET /api/v1/batches/options` lists configured providers, installed Ollama models,
the default Gemini model, themes and limits. These routes and typed contracts
are described in the application's OpenAPI schema.

### Alternative local model: ISTA-DASLab Qwen 27B

The user reports running
`hf.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:IQ2_XS`
(approximately **9.4 GB** in `ollama ls`) with a **65,536-token context window**
and generation at approximately **20 tokens per second**. This is a user-reported
observation, not a reproducible project benchmark or a hardware-independent speed
guarantee. GPU/VRAM details and actual GPU/CPU offload were not recorded.

The user also reports VRAM pressure high enough that this setup requires stopping
the graphical desktop to free GPU memory. The 9.4 GB figure is the listed model
size, **not total runtime VRAM usage**: KV cache, compute buffers and other GPU
applications need additional memory. This is a limitation of the reported machine,
not a universal requirement to disable or uninstall a GUI. Stopping a desktop can
end graphical sessions and lose unsaved work; no desktop/service changes are made
by the application or the documented model selection.

The supplied `systemctl show ollama -p Environment` output lists:

```text
OLLAMA_CONTEXT_LENGTH=65536
OLLAMA_KV_CACHE_TYPE=q4_0
OLLAMA_FLASH_ATTENTION=1
OLLAMA_NUM_PARALLEL=1
OLLAMA_MAX_LOADED_MODELS=1
```

**`IQ2_XS` quantizes the model weights; `q4_0` configures the KV cache, not Q8.**
27B refers to model parameters, not context length. The service environment
configures defaults and does not by itself prove the effective settings of a
particular running request. An explicit request can override the default context;
check `ollama ps` and runner logs when verifying an actual run.

To select this installed model explicitly, use these upload options:

```json
{
  "llm_provider": "ollama",
  "ollama_model": "hf.co/ISTA-DASLab/Qwen3.8-27B-GSQ-RCO-GGUF:IQ2_XS",
  "ollama_context": 65536,
  "template_name": "modern_sidebar",
  "export": true,
  "allow_fallback": false
}
```

Save the object as a local `options.json` and pass `upload --options-file options.json`
to the [CLI](../scripts/batch_api.py). This replaces the CLI's default options object;
it does not change the server's default model or existing tasks. Discover installed
models first with `GET /api/v1/batches/options`. The report above is not evidence
that this model completed the application's full analysis/export pipeline.

## Responses, polling and idempotency

`202 Accepted` returns `task_id`, `status_url`, `view_url`, `Location` and
`Retry-After: 3`. Poll `GET status_url` with the session cookie. `result.items`
contains incremental per-offer results with analysis, preview and download links
where available. Open `view_url` for the normal progress page, then History.
API links include the configured application root path; resolve them against the
server origin. Responses use `Cache-Control: no-store`.

Each item may include `offer_valid_until`, an optional publisher calendar date
(`YYYY-MM-DD`, otherwise null). It propagates to the child analysis and saved
application. A past date is informational and does not stop processing; no
deadline is inferred from publication age. See [offer deadlines](offer-deadlines.md).

The batch's `completed` means iteration finished, **not that every offer succeeded**:

| Item status | Meaning |
| --- | --- |
| `queued` / `running` | Not finished yet |
| `completed` | PDF/DOCX available through `preview_url`, `pdf_url`, `docx_url` |
| `draft_ready` | Analysis/draft saved; export was disabled |
| `manual_required` | Blocked/expired/unsafe offer; inspect `error`, paste a description in the UI if appropriate |
| `review_required` | Export validation or summary confirmation needs attention; open `analysis_url` |
| `failed` | Processing failed/timed out; saved analysis, if present, remains accessible |

The same `Idempotency-Key` (8–128 letters/digits/`._:-`) and normalized payload
returns the same batch, including after completion (`200`), without generating
again. A changed payload returns `409`. Lookup/admission is serialized across
processes. Use a new key for an intentional rerun, preferably just failed URLs.
Other errors: `401` unauthenticated, `403` CSRF/origin/demo denied, `413` oversized
HTTP body, `422` invalid input, `429` rate/queue admission limit, `507` account
storage or file-count quota reached.

`429` also reports an exhausted **application daily AI call budget**, including
for local Ollama, with `Retry-After` until the 00:00 UTC reset. New batches are
rejected before queueing; existing idempotent results remain readable. If the
budget runs out mid-batch, completed results are retained and later URLs are not
fetched. Affected items use `error_code=daily_ai_budget` and
`retry_after_seconds`; see [daily budget behavior](batch-budget-behavior.md).

## Security and operational limits

- Demo submissions are disabled. Reads and tasks use the account-local runtime;
  no cross-account task lookup or new authentication mechanism is introduced.
- Session-bound CSRF, origin checks, early request-body limits, rate limiting,
  daily AI budgets and disk quotas remain active. A TXT file is parsed as text,
  not executed or saved under its client-supplied filename.
- Each URL goes through the existing SSRF-safe extractor, including public-IP
  validation, DNS pinning, redirect checks and guarded browser fallback. Local,
  private and metadata addresses do not reach transport. The batch does not
  bypass portal protections; blocked offers require manual input.
- Each offer has the configured task deadline. The batch deadline is the sum of
  bounded per-offer deadlines plus 60 seconds. Failures do not stop later offers.
- Truth Lock stays enabled. AI summary confirmation is **never automatic**:
  open the returned analysis, review/confirm and export. Layout failures similarly
  retain the draft instead of weakening export checks.
- Batch fallback is opt-in (`allow_fallback: false` by default). A primary explicitly
  selected as Gemini still transmits data to Google; choosing `ollama` and leaving
  fallback disabled keeps generation local. Explicit fallback permission is also
  bounded by global settings. Older deployments without this option follow the
  global preference; disable cloud fallback in settings if inappropriate.
- Restart recovery marks unfinished work failed; it does not silently rerun paid
  work. Completed items and drafts remain available. No migration, dependency,
  new environment variable, service or deployment is required.

## Tests

Run from the repository root:

```sh
.venv/bin/pytest -q tests/test_batch_models.py tests/test_batch_security.py tests/test_batch_api.py \
  tests/test_batch_fallback_policy.py tests/test_batch_security_audit.py tests/test_draft_export_transaction.py
.venv/bin/ruff check .
```

- `test_batch_models.py`: URL validation/canonicalization, deduplication, count
  before deduplication, BOM/UTF-8/size, option constraints and Gemini model names.
- `test_batch_security.py`: session/CSRF/origin rejection, upload/options abuse,
  demo denial, queue/body limits and wrong-kind/malformed task IDs.
- `test_batch_api.py`: OpenAPI/discovery, idempotency across workers, normal
  history/drafts, per-item partial failures, confirmation-required handling,
  real synthetic PDF/DOCX generation/downloads, real SSRF guard before transport,
  task-local Gemini selection and restart recovery.
- Existing `test_job_extractors.py` and `test_browser_extractor_security.py`
  cover the shared extractor security boundary in greater depth.
- The fallback-policy, security-audit and export-transaction tests cover explicit
  cloud consent, legacy child retries, cross-session CSRF replay, quota rechecks
  and staged publication/rollback. See the [security review](security/batch-api-audit-2026-11-03.md)
  for findings, fixes and residual limitations.

Tests use synthetic profiles and mock external services; they do not prove that
live portals or paid providers are currently available. Review every generated
CV before applying. The API does not submit job applications for you.
