# CV content quality repair

Base: `a84af39`; branch: `codex/cv-content-quality`. No main merge, production deployment, data edits, model/provider configuration or infrastructure changes.

## Causes and changes

1. Profile descriptions and facts already contained overlapping descriptions of the same Linux VPS / ML pipeline. `_project_description` selected two highly ranked statements and concatenated them. Rendering did not create the duplicates. `content_quality.py` now removes exact and conservatively entailed repetitions and combines equal action/object cores with literal distinct qualifiers. The VPS description retains SSH and n8n in one sentence; the ML description retains model comparison while removing the redundant pipeline-construction sentence.
2. `FactCatalog.supports_paraphrase` deliberately permits only exact source text. Consequently valid natural model summaries were mechanically replaced. The PDF fit stage independently replaced summaries to force one page. Ollama/Gemini now optionally review a non-verbatim summary against supplied facts, without job text as evidence. A server HMAC binds approval to text, citations, identity and professional profile facts. `FactValidator` preserves verified wording; pagination never regenerates a summary or strips its evidence/level-labelled skills.
3. Some Ollama-compatible servers do not enforce schema `minItems`. The live model omitted summary citations. A reviewer can recover exact citations from the actual profile; unknown IDs or unverifiable claims receive no approval. Exact source wording needs no extra call. Rejected/unavailable review keeps the conservative fallback, never selects a different provider or bypasses Truth Lock. The optional review has a 30-second deadline.
4. Automatic export preparation used to strip Hands-on labels. Original qualifiers (including Basic/Junior/Hands-on) are now retained; bare duplicate skill labels yield to the qualified label. Deterministic checks reject obvious unsupported expertise/CEFR upgrades, unfinished/empty experience fragments and invalid links. Cross-section repeats and ambiguous same-evidence wording are review hints, not reasons to delete true facts.
5. Valid ASCII link targets are kept byte for byte. Display wrapping/decoded labels are separate from href values. Project/contact targets are still checked in PDF annotations and DOCX relationship XML.

## Conservative deduplication

Removal requires compatible action/object structure, ordered concept containment and unchanged negation, numerical values, proficiency, implementation/production/local scope. Different actions, participants or novel qualifiers survive. Equal bases with different tools retain both literal qualifiers. Word overlap alone cannot delete a statement. Experience deduplication unions source IDs. The source profile is never changed.

The deterministic pre-export gate is shared by PDF and DOCX. It cleans repeated prose and reports quality issues, and blocks empty/unfinished experience or obvious level elevation. A model's declaration of approval cannot grant an attestation. Edits to prose, citations or professional facts invalidate it; unrelated contact changes do not. Rejected/incomplete summaries still use attested fallback text, so not every output can be promised fluent paraphrasing when the model/reviewer is unavailable.

## Storage/compatibility

The TailoredResume JSON contract is unchanged; the attestation is a private attribute, absent from the model generation schema and exported CV JSON. It persists in optional workflow/generated metadata, which older readers ignore. Existing drafts/CVs require no migration. Draft loading, save/load, editing and baseline restoration preserve the relevant review metadata. No SQLite/schema or profile/skills migration is required.

## Validation

- Full final local suite: **410 passed**, 48 existing Starlette/AnyIO deprecation warnings.
- Ruff and `git diff --check`: passed.
- Provider tests cover Ollama and Gemini, optional review failure/timeout, citation recovery, signed approval and forged/stale text. Storage and pagination tests prove the natural paragraph survives reload and fitting.
- Dedup tests preserve different actions, actor order, numerical facts, local/production scope and levels; they reproduce the VPS/ML duplicates. Basic/Junior labels and B2/CEFR guards are covered.
- Existing pagination fixtures were changed from repeated identical filler to distinct numbered facts. They still assert retention of all 600 accented statements, text reading order and whole project blocks. Deliberately repeated filler should now deduplicate rather than artificially create more pages.
- Generated PDF: one page, inspected through Poppler; DOCX: two pages rendered through LibreOffice. Photo, all jobs, degree/language/contact text, hyperlinks and consent were checked. Synthetic long URLs stay inside margins and remain fully clickable. Native PDF and DOCX relationship targets remain exact; LibreOffice's PDF conversion adds `/` to a root URL without changing its resource.
- Same saved model response compared against the base code and branch: VPS/ML repetitions disappear while distinct tools and model-comparison evidence remain. Neither saved history nor the original CV was overwritten.

## Real model trial and limits

A full direct-provider generation ran with the configured Ollama `qwen3.5:9b`. Analysis initially exhausted 8192 tokens and used the existing one-retry path. Analysis plus tailoring/export took **733.48 seconds**. Reviewing the same real model paragraph on the final citation-recovery path took **14.85 seconds of model time**, **29.13 seconds including final validation/fitting/exports**; the paragraph was approved and retained verbatim. No live Gemini API was called.

Normal call count is analysis + tailoring, plus one conditional summary review. This trial had four model calls including the pre-existing analysis retry. The direct-provider trial bypassed the queued task's 720-second budget: this long-offer run exceeded that budget even before optional review. Therefore it confirms model/output/export quality, not that this exact long job will finish through the production queue within its current deadline. Model/context settings and timeouts were not raised. Long analysis/queue latency remains a performance limitation requiring separate work.

Private artifacts: `/root/cvtailor-pr-artifacts/content-quality/`. Real generated `cv.pdf`/`cv.docx`, before/after saved-output comparisons, extracted text, live timings and long-link renders are stored there, not committed to GitHub.
