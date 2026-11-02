# Batch CV API

The owner-only API processes explicitly selected job URLs **sequentially**, without
discovering/crawling additional offers. It saves ordinary analyses/drafts in
**History** and optionally generates PDF/DOCX using the normal export pipeline.

## Authentication and file submission

Use the existing session cookie and session-bound CSRF token. There are no bearer
tokens or anonymous access. Use HTTPS outside local development. Protect cookie
files: they grant account access. Do not commit cookies, URL lists or generated CVs.

Prepare a UTF-8 TXT file (optional BOM), one URL per line or whitespace-separated.
Maximum: 20 input URLs, 64 KiB. Canonical duplicates are processed once, in order.
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
  -F 'options={"llm_provider":"ollama","ollama_model":"gemma4:latest","template_name":"ats_classic","tailoring_level":0.3}' \
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
  "ollama_model": "gemma4:latest",
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

`GET /api/v1/batches/options` lists configured providers, installed Ollama models,
the default Gemini model, themes and limits. These routes and typed contracts
are described in the application's OpenAPI schema.

## Responses, polling and idempotency

`202 Accepted` returns `task_id`, `status_url`, `view_url`, `Location` and
`Retry-After: 3`. Poll `GET status_url` with the session cookie. `result.items`
contains incremental per-offer results with analysis, preview and download links
where available. Open `view_url` for the normal progress page, then History.
API links include the configured application root path; resolve them against the
server origin. Responses use `Cache-Control: no-store`.

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
HTTP body, `422` invalid input, `429` rate/queue/storage admission limit.

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
- Existing fallback preferences apply. `auto` uses the configured primary, not
  necessarily local inference. Gemini primary **or fallback** transmits job and
  candidate facts to Google. Disable cloud fallback in settings if inappropriate.
- Restart recovery marks unfinished work failed; it does not silently rerun paid
  work. Completed items and drafts remain available. No migration, dependency,
  new environment variable, service or deployment is required.

## Tests

Run from the repository root:

```sh
.venv/bin/pytest -q tests/test_batch_models.py tests/test_batch_security.py tests/test_batch_api.py
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

Tests use synthetic profiles and mock external services; they do not prove that
live portals or paid providers are currently available. Review every generated
CV before applying. The API does not submit job applications for you.
