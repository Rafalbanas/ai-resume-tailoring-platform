# Exact token usage

CVTailor shows provider-reported token statistics after each completed model call and keeps the final totals on the draft analysis and comparison results. While a call is running, it displays that statistics are pending; it does not estimate tokens from streamed text, chunks, characters, or elapsed time. Ollama remains non-streaming with the existing model, thinking and token budgets.

Ollama input/output counts come from `prompt_eval_count` / `eval_count`. Generation speed is `eval_count / (eval_duration / 1_000_000_000)`, excluding prompt processing and model loading. The displayed speed belongs to the last completed call, not the entire job. Gemini uses its final `usageMetadata` counts and `totalTokenCount`; no generation speed is invented when the provider does not expose it.

A task-scoped collector aggregates calls including Ollama recovery and Gemini HTTP attempts. Unknown usage remains unavailable; failed attempts without usage produce a clearly marked partial total. Task records retain numeric telemetry across refreshes. The draft stores the final snapshot in the backward-compatible `WorkflowResponse.token_usage` field. No prompt, generated content, candidate fact or credential is copied into these statistics. Concurrent tasks have independent collectors.

Verification covers exact end-of-call counts/speed, unavailable failed-call usage, retry totals and concurrent-task isolation. Existing provider/task/comparison tests also passed. A small actual qwen3.5:9b request reported 179 input tokens, 6 output tokens, 185 total and 52.3 output tokens/s; those are real API metrics, not a simulated analysis.
