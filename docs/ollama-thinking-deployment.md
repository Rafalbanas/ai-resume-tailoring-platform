# Bounded Ollama thinking review

Analysis, recovery, CV generation and the existing summary check use `think: false`.
With `OLLAMA_DRAFT_REVIEW_ENABLED=true` (the default), one optional `think: true`
request reviews the completed analysis and CV draft before the summary check.
It never repeats the whole analysis or generation stage.

The review checks up to four missing/partial/absent requirement assessments and
up to sixteen existing experience bullets. It can correct gap explanations and
assessments, subject to the existing semantic source/evidence validator. It cannot
change requirement names, source quotes, priorities, tenure, proficiency or
AND/OR structure. Component corrections go through the existing aggregation.

The reviewer judges existing bullet text against its cited employment facts and
the advertisement. It cannot generate new bullet text or change citations.
Supported, relevant paraphrases receive a server-generated HMAC bound to the exact
text, citations and current profile. Truth Lock checks that approval independently
of model output; unapproved wording retains the existing source-text fallback.
Changing the text, citations, profile or signing key invalidates approval. Employer
identities and dates still come from the profile. Approvals survive draft saving,
export and history loading, but are never accepted as public resume JSON fields.
Irrelevant/rejected bullets are omitted when other approved descriptions remain;
otherwise one entry is retained for the normal source-validation fallback.

## Budgets and failure behavior

The optional review has a 2048-token output budget and a 60-second total deadline,
including admission/semaphore waits. There are no review retries or review-triggered
provider fallbacks. Timeout, truncation, invalid evidence, incomplete/duplicate
verdicts or invalid analysis leave the first-pass result intact. A cancelled outer
task still cancels the review. Review is skipped when completed provider calls
already consumed 480 seconds; the global task/operation limits remain unchanged.
Call metrics record the review stage, whether thinking was requested/returned, and
whether the review was accepted, discarded or timed out. An accepted review does
not establish universal model accuracy.

## Incident and deployment

Unconditionally enabling thinking on 2026-10-22 caused three observed calls to
consume all 8192 output tokens, approximately 166 seconds each. The enclosing task
failed at its 720-second limit. A tiny arithmetic smoke test had confirmed thinking
availability but had not tested this workload. Unrestricted thinking was disabled
on the VPS while this bounded review was prepared.

A separate CI failure in `test_native_deadline_kills_the_process_group_and_releases_slot`
was a procfs race: the process could disappear during `/proc/PID/stat` reading.
The test now treats `FileNotFoundError` and `ProcessLookupError` as successful
termination while still rejecting a surviving process and checking slot release.

The temporary production volume `ollama-thinking-code` overrides
`/app/app/services/ollama_provider.py` from a ConfigMap. Remove that mount and volume
when deploying an image containing this change; otherwise it masks the image's
provider implementation. Delete unused `cvtailor-ollama-thinking-*` ConfigMaps only
after the new image is healthy. The demo and historical CVs are not rewritten.
