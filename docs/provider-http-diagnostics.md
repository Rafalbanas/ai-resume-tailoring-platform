# Ollama HTTP diagnostics

Failed Ollama requests now preserve HTTP status, a fixed error category and explanation, UTC start time, client duration, endpoint, request/schema/response byte counts, prompt character count, configured context/output budgets and thinking mode. Counts describe the request actually sent; character/byte counts are not measured input-token usage. A response fingerprint supports comparison without retaining its content.

Each call has a generated `call_id`, sent as `X-Request-ID` and included in the safe failure message and application warning log. Model-server/proxy logs can correlate it if configured to log that header. Diagnostics include the owning task ID and a task link. Failed primary HTTP calls survive successful fallback and dual-provider failure, in saved workflow results or the failed task's diagnostic run.

The authenticated Diagnostics page shows HTTP status and error explanation per call, including failed Ollama calls followed by successful Gemini fallback. Existing diagnostic entries still render; new fields cannot reconstruct missing historical HTTP status or response data.

Categories include context budget, memory allocation, missing model, schema/grammar rejection, authentication, rate limiting, missing endpoint, invalid request and server error. Categories come from bounded matching of server error text and status, not a guaranteed root-cause diagnosis. Unknown errors remain generic; inspect server logs using the timestamp and call ID. Simply mentioning “context” no longer proves a context-window overflow.

Raw response bodies, prompts, CV facts, authorization headers and credentials are never added to diagnostic metrics. Error explanations come from a fixed dictionary. The bounded HTTP response is inspected only in memory; only its size and SHA-256 are retained. No extra model calls are introduced.

Validation uses synthetic responses and `httpx.MockTransport`, covering error categories, non-HTTP failures, request sizes/IDs, confidentiality, fallback and dual-failure persistence, task linkage, and legacy/new diagnostic rendering. The earlier matching/history changes were published first in PR #63; diagnostics are an additional commit in that PR.

Local verification on the PR branch: 153 focused tests passed, including 21 new HTTP-diagnostic cases. The previous matching/history commit passed 224 focused tests on current main. Ruff, diff whitespace checks, README synchronization and `pip check` passed. The local environment version check still reports pre-existing drift for FastAPI, pydantic-settings, Playwright and Ruff; the PR's full CI results must be checked separately.
