# Source analysis and export correction — 2026-10-11

The saved Reply Customer Service Consultant description contains nine responsibilities and four TECH STACK entries. It contains no candidate qualifications, required levels, or statement that previous Dynamics experience is mandatory. The saved comparison used the same description as the saved CV. Its Ollama result contained two mandatory requirements; Gemini contained ten, including duplicate product references and duties promoted to prerequisites.

The previous comparison persisted only validated results. Its raw model responses and exact serialized requests are unavailable. The generation/parsing contribution to the original 2-versus-10 difference cannot be determined retrospectively. They have not been reconstructed.

## Established causes

- Source extraction found no qualification section, then the validator's fallback accepted model suggestions from duties as mandatory requirements. TECH STACK was discarded. Source coverage therefore depended on the model's chosen subset.
- Matching used literal names and bank aliases for generic support competencies, although the analysis payload already included all employment fact bullets. Partner support and incident resolution were not recognized as equivalents of customer support and problem solving.
- Skill ranking prioritized requested IDs and their order over job relevance, while prompts and Ollama's schema encouraged at least eight selections. A no-bank fallback also used a fixed first-ten list.
- Summary validation replaced every generated summary unconditionally. Its replacement used only summary facts and the role title, excluding relevant employment facts and the full description.
- Normal-flow consent could paginate alone. The layout measurement still expected an absolute footer, making its destructive one-page fitting decisions unreliable.
- Benchmark claims did not distinguish model text from replaced sections or account for provider-specific response schemas and model-dependent analysis in resume inputs.

## General behavior after correction

Source headings distinguish qualifications, preferences, responsibilities, organization context and listed role competencies. Listed competencies have unspecified required levels; they are displayed with evidence, excluded from qualification scoring, and do not establish mandatory previous experience. Missing qualifications or uncovered requirement-bearing passages produce **Incomplete analysis — review required**, UNRELIABLE / RETRY.

Conservative semantic normalization deduplicates equivalent source requirements and keeps every original quotation. Product knowledge and configuration experience remain separate. The evidence matcher recognizes generic support and problem-solving equivalents through existing employment facts, with source IDs and literal evidence. Titles and employers do not establish competence. General CRM evidence cannot establish additional products or methodologies. Confirmed, partial, not confirmed and explicit confirmed gaps remain distinct.

Eligible skill ranking follows job relevance before model preferences, without a minimum or irrelevant padding. Profile/bank levels are unchanged. The headline uses the verified occupation and selected capabilities. Unsupported target-role credentials are not asserted.

A summary is retained only when its source IDs and text resolve to verified source sentences. Otherwise the validator selects relevant summary/employment facts using the full job description. It does not relax paraphrase validation or change subjectless English sentences to third-person prose. Replacements explicitly invalidate comparisons of model tone.

Comparisons now preserve raw responses and actual payloads privately, with prompt/payload/schema fingerprints, parsed model output, validated output, changed section names and token metrics. Captures are scoped to each comparison task. Task files are created with mode 0600; candidate content is not added to repository files or application logs. Comparison uses the two direct providers with fallback disabled and Gemini retries disabled on a local copy, preserving global settings.

Consent is running PDF margin content, repeated on actual content pages. Both layouts reserve room for it. DOCX uses its actual footer in the simplified layout. PDF fitting changes spacing only; it never deletes or truncates facts to force one page. Continuation pages in Modern Sidebar have a top margin.

## Targeted tests

114 tests passed in 21.21 seconds across the twelve targeted modules. Ruff and `git diff --check` passed. Coverage includes obligation/prerequisite separation, semantic duplicates and distinct configuration requirements, support/incident evidence, unconfirmed Dynamics/KCS, explicit gaps versus profile silence, incomplete-analysis recommendations, job-dependent skill ranking without padding, retained subjectless source summaries, replacement labels, private capture before parsing, quota/no-retry isolation, PDF footer bounds and DOCX footer preservation.

## Saved-data and one-run verification

After source review: **0 mandatory qualifications, 9 responsibilities, 4 listed competencies**. CRM, Customer Support, Problem Solving and IT Support are confirmed by existing evidence. Dynamics experience is not confirmed, and the duties do not make it a mandatory prerequisite. No confident application/rejection recommendation is issued from this source.

Only one new workflow per provider was run, each with an analysis call and a resume call. No fallback, retry, or global model change occurred. Both models still inferred prerequisites from duties before validation; the validator prevented those in the final output. Their actual payloads and system prompts were identical for both stages; schemas differed. Identical replacement summaries therefore do not establish identical model tone.

| Provider | Workflow time | Input tokens | Output tokens | Total tokens |
| --- | ---: | ---: | ---: | ---: |
| Ollama | 55.423 s | 6,656 | 2,475 | 9,131 |
| Gemini | 6.158 s | 6,757 | 2,036 | 8,793 |

Both new CVs select eight relevant confirmed skills, including Salesforce, incident handling, support, technical troubleshooting and documentation. Both use a verified support occupation with incident handling and Salesforce in the headline. Both generated summaries required replacement. Ollama had five validation messages (summary, three project descriptions, one project technology removal); Gemini had eight (summary, six experience bullet replacements, one project description). Exact before/after section differences are recorded separately from message counts, including canonical source IDs, dates, education and verified interests.

New results are stored separately in generated folders ending `_2` (Ollama) and `_3` (Gemini). The earlier CV and comparison remain unchanged. Detailed private evidence, model snapshots, export checks and rendered page images are under the ignored `data/.diagnostics/reply-fix/` directory and the new comparison task.

Visual inspection covered all pages of the original PDF, both new models' two PDF themes, short/long/saved-content checks for both themes, and LibreOffice-rendered DOCX for the same content. The original had a consent-only second page. The saved content now uses one page in Modern Sidebar and two in ATS Classic, without deleting facts. Short documents use one page in both themes; expanded documents use two in Modern Sidebar and three in ATS. DOCX remains a simplified one-column layout, with short/saved/long checks using one/two/three pages. No corrected export has a consent-only page, overlapping footer, or clipped consent.

## Changed files

- Analysis/evidence: `app/models/job.py`, `app/services/job_sections.py`, `app/services/grounded_requirements.py`, `app/services/analysis_validator.py`.
- Resume selection: `app/services/skills_bank.py`, `app/services/fact_validator.py`, `app/services/professional_summary.py`.
- Model inputs and benchmark: `app/services/ai_provider.py`, `app/services/ollama_provider.py`, `app/services/gemini_provider.py`, `app/services/comparison_capture.py`, `app/services/task_manager.py`.
- Export/UI: `app/services/pdf_generator.py`, `app/services/docx_generator.py`, `static/resume.css`, `templates/resume.html`, `templates/analysis.html`, `templates/compare.html`, `templates/resume_preview.html`.
- Changed tests: `tests/test_reply_mechanisms.py`, `tests/test_compare_and_diagnostics.py`, `tests/test_gemini_provider.py`, `tests/test_ollama_provider.py`, `tests/test_pdf.py`, `tests/test_resume_workflow.py`, `tests/test_skills_bank.py`, `tests/test_task_manager.py`. Existing source-section, matching, fact-validator and layout coverage also ran. Session login was corrected only in test setup; production authentication was not changed.

## Limits

The source lacks qualifications and has no saved offer URL; it cannot establish conditions absent from that description. Semantic deduplication is conservative and does not automatically equate arbitrary paraphrases or discard different proficiency/action conditions. Exact pre-validation behavior of the old comparison is unavailable. DOCX was visually checked in LibreOffice, not Microsoft Word. No full audit, additional model run, deployment, authentication change, license change or connection-setting change was performed.
