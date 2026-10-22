# Ollama thinking deployment — 2026-10-22

Ollama requests now send `think: true` for analysis and CV generation. The model
remains `qwen3.5:9b`; production retains its 8192-token output limit, 32768-token
context and 540-second read timeout. Thinking consumes output tokens, so compare
real analysis completion and accuracy before adjusting these limits.

The production `cvtailor` deployment currently mounts the updated provider from
immutable ConfigMap `cvtailor-ollama-thinking-0f47671e2aee`, using volume
`ollama-thinking-code` at `/app/app/services/ollama_provider.py`. The mounted file
was copied from the running image and differs only in the thinking flag. This
preserves the running release and avoids deploying unrelated workspace edits.
The demo deployment was not changed.

The source change must be included in the next application image. Once that
image contains `think: true`, remove this volume mount and volume from deployment
`cvtailor` before verifying the rollout; otherwise the mounted provider would
mask future image updates to that file. Delete the ConfigMap after the mount is
removed. To revert this deployment before that release, remove the mount and
volume and verify the rollout: the underlying image still sends `think: false`.

Validation: all 45 Ollama provider/token-budget tests passed, targeted Ruff
checks passed, deployed source matched the tested file, and `/health` returned
HTTP 200 after rollout. Deployment used the existing admission lock and checked
that neither main nor demo had queued/running analyses.

A synthetic request through the deployed provider returned the correct answer
42 for 17 + 25, `thinking_present=true`, `done_reason=stop`, and 169 completion
tokens in approximately 6.47 seconds. This confirms thinking works through the
actual Ollama connection; it does not establish improved CV analysis accuracy.
