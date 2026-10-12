# Offer-specific CV content selection — 2026-10-12

Baseline: `8816e0d`. Master profiles, skill levels, employment dates, provider/model defaults and saved CVs are unchanged.

## Findings and implementation

Both Ollama and Gemini previously received a support-first summary instruction and a target-title placeholder. The export boundary then always substituted the current occupation. Only the first ten requirement names reached the tailoring stage: their priority, provenance and supporting facts were absent. Fallback experience selection chose relevant bullets but restored source order; fallback projects always used a generic description. This made a DevOps CV resemble a support CV.

- `ai_provider.py`, `ollama_provider.py`, `gemini_provider.py`: one provider-neutral tailoring prompt, all interpreted requirements with original quotes/priority/status/levels/source IDs, role competency evidence, and eligible skill levels/evidence. No extra model calls. Models select emphasis and factual source sentences for each offer; there is no employer/role-specific template.
- `fact_validator.py`: use the model's cited evidence/requirement ordering to rank existing facts; resolve skills back to documented usage; retain eligible model-selected skill order. Preserve employment chronology and all roles. Include relevant attested facts omitted from experience, with a maximum of four bullets per role. Accept the real occupation plus at most two exact eligible skill wordings; reject an unheld target title and unsupported expertise. Rank projects and select up to two complete relevant source sentences. Preserve actual project URLs and factual source IDs.
- `professional_summary.py`: a support mention inside a different advertisement no longer forces a support summary. Non-support fallback starts with relevant evidence, retains employment identity and avoids consuming every sentence with the same leading requirement.
- `job_sections.py`: ranking hints separate qualifications/duties/competencies from benefits; unknown sections remain available. The full original advertisement still reaches the LLM.
- `semantic_requirements.py`: a literal multiline benefits quote remains context even when an AI combines adjacent lines.
- `resume_export.py`, `pdf_generator.py`, `docx_generator.py`, `templates/resume.html`: recognizable host/path labels for project links; complete targets, including query parameters, remain hyperlinks. Existing styles, photo handling, pagination/overflow checks and visible searchable contact text remain.
- `task_manager.py`, `routes/web.py`: pass the saved validated analysis into final content validation. Manual editing keeps its existing validation path.

No schema migration or contract changes are required. Existing Pydantic resume fields and saved JSON remain compatible.

## Truth boundary

Only supplied source facts and eligible existing skills can reach export. Ranking is not proof of competence and never changes levels. Basic Docker/Bash remain basic; B2 does not become fluent/C1. Planned project claims cannot become deployed features; a workflow file is not a production CI/CD claim. Unsupported paraphrases still fall back to complete attested facts rather than being approved by keyword similarity. Job requirements never become candidate facts. No candidate bank/profile data was edited.

## Validation

Full regression run: **385 passed**, 48 existing Starlette/AnyIO deprecation warnings. After the final summary diversification adjustment: **77 relevant tests passed**, plus **47 summary/export/section tests passed**. `ruff check .` and `git diff --check` passed. New tests cover offer-specific evidence ordering, preserved source facts, basic skill levels, rejected expertise/unheld titles, all requirements in payload, incomplete/no-project profiles, long project links and both PDF templates.

The editing regression now checks every bullet against original attested facts, rather than requiring one source-array index, because relevance ordering intentionally changes bullet positions. Its truth assertions were strengthened, not removed.

## Before/after comparison and artifacts

The baseline uses the actual validator/renderers from `8816e0d`, not raw unvalidated AI output. Both versions use the same saved profile and model response.

- Junior DevOps: baseline summary was support-first and identical to support. New summary starts with documented Linux VPS work, Windows Server/VMware deployment and Python/HTTPX/JSON integration; actual employment remains explicit. The headline retains the real occupation and adds Linux administration/basic Bash. Linux VPS precedes the application project; the ML project follows. No commercial DevOps tenure, Kubernetes or cloud expertise was invented.
- Technical Support: keeps troubleshooting, incident handling, SQL/API and professional English. Support-relevant projects lead; the ML project is not selected for this example, while its education/thesis evidence remains. Every role and degree is retained.
- Both examples: one-page PDF, readable two-page DOCX rendered by LibreOffice, original photo, visible/working contacts and project hyperlinks. PDF text extraction and DOCX XML/text extraction preserve employer names, roles, qualifications and consent. PDF geometry/overflow checks pass. Independent Poppler visual inspection confirms the PDF layout.

Artifacts: `/root/cvtailor-deploy-backups/tailoring-quality-20261012/{devops,support}-{before,after}/cv.{pdf,docx}`. Validation details and extracted text are beside the documents. These are isolated examples: existing application history/exports were not overwritten.

## Limits

No new live Ollama/Gemini generation was run. Mock-provider tests verify contracts and truth properties, not live wording quality. Examples demonstrate post-processing of previously saved model outputs; the new prompt still needs real-model evaluation on a future user generation. The number of model calls remains the existing analysis + tailoring pair; no new validation/model call was added. No generation-speed improvement is claimed.
