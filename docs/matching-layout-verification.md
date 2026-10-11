# Matching, resume layout and English UI verification — 2026-10-11

## Diagnosis and preserved history

The latest saved Motorola Solutions / Technical Support Specialist draft was `e5d681b9696646fbac01cbb5553f42f9`; the existing generated entry and all earlier drafts/CVs were preserved. Its result had three rows, all classified mandatory: one partial and two missing. The old recommendation counted all three non-strong rows as mandatory blockers, producing LOW / SKIP. Thus “three blockers” included a partial match; it was not three independent confirmed absences.

The full saved job description contains 5,771 characters. The old compact analysis payload sent 4,952 characters after removing administrative/EEO material; the actual requirement sections remained present. The loss was not explained by that cleanup. The structured-output schema allowed empty or incomplete requirement lists and did not enforce coverage of source sections. No original raw response was retained: saved drafts/tasks contain the result after parsing and normalization. The exact model output cannot be reconstructed as fact.

The deterministic source parser required a colon after a requirements heading and did not recognize `Basic Requirements`, `Essential Skills & Requirements`, or the long `Preference will be given…` heading. Consequently no source requirement lines were recovered. Normalization fell back to the model-suggested claims/source-quote extraction, which defaulted to mandatory and shortened quotes. Organization prose entered this fallback; preferred certificates became mandatory; CRM/KCS remained combined. Completeness validation accepted any nonempty result unless the text visibly ended unfinished. Matching and scoring operated on these three normalized rows, and the UI displayed that saved result. This is a source parsing, normalization and coverage failure, with permissive schema validation; unavailable raw output limits any attribution to the model.

## General changes

- Recognize mandatory, preferred, responsibility and organization sections without relying on colons or a particular employer. Administrative sections stop extraction.
- Recover every assessable source unit, regardless of model omissions. Each requirement keeps its full original quote, source section, classification basis and scoring group.
- Split independently evidenced CRM/KCS and fluency/customer communication clauses. Their shared source group prevents double-counting. Alternatives and certification examples do not require every listed item. Inline `preferably` qualifiers remain optional.
- Verify against profile facts and eligible skill evidence, without inferring competence from title/employer. Distinguish confirmed, partial, unconfirmed and explicitly documented absence. B2/daily English is partial evidence for fluency.
- Check omitted source units and uncovered requirement-bearing passages, including outside recognized sections. Incomplete results become UNRELIABLE / RETRY and display “Incomplete analysis — review required”. Silence in the profile alone does not produce a firm SKIP. Preferences do not create mandatory blockers. Fact validation and Truth Lock remain active.
- Make Modern Sidebar / ATS Classic available before first export, in preview and in saved-CV editing. Persist selection per CV, validate identifiers and regenerate PDF/DOCX directly from unchanged saved content. Theme-only edits bypass AI and fact rewriting. Legacy entries keep Modern Sidebar as their default. ATS excludes photos; returning to Modern remembers its preference.
- Correct Modern Sidebar print flow: long content continues on another page instead of being clipped at A4. Include saved interests in both themes. No destructive one-page shortening is applied when changing layout or saving edits.
- English controls, placeholders, account/login/logout, task messages, fallback labels, errors and validator explanations. New model prompts request English generated reasoning. Stored profile, evidence, quotes and old resumes are untouched. Old analyses are labeled “Original analysis”; saved task labels are translated only for display.

## One isolated full Ollama trial

One full analysis + resume generation used the unchanged configured `qwen3.5:9b` model. Fallback was disabled only on the isolated router for this run; global provider settings were not changed and Gemini was not called. Both theme exports were rendered from the same fact-validated generated content without another model generation.

The new history entry is `2026-10-11_motorola-solutions_technical-support-specialist_2`; its draft is `aa7ca74fafb84f85a2c2724624f05be1`. No old entry was overwritten. Hash checks confirmed all pre-existing data files unchanged. A separate deployment baseline also confirmed data/config files unchanged; temporary verification sessions were revoked.

| Category | Old saved result | New source-backed result |
|---|---:|---:|
| Mandatory assessed units | 3 | 10 |
| Preferred assessed units | 0 | 7 |
| Confirmed | 0 | 4 |
| Partial | 1 | 4 |
| Not confirmed | 2 | 9 |
| Confirmed absence | 0 | 0 |
| Separate responsibilities | 0 | 8 |
| Separate organization passages | 0 | 2 |

The 17 assessed units represent nine mandatory and six preferred source lines; two compound lines were split for independent evidence while retaining shared scoring groups. The numbers are derived from this source, not fixed thresholds in code.

Result: **LOW / REASONABLE_STRETCH**. Four units are confirmed, four partial, and nine not confirmed. Nine mandatory units require review (partial or unconfirmed); preferences do not block application. This assesses documented evidence, not hiring probability or an ATS score. The score was not artificially raised.

Unconfirmed mandatory units: the specified 2+ years in support/customer service/helpdesk; explaining technical concepts gracefully to customers of all levels; the full data/log-analysis and multitasking condition; independence combined with teamwork; the specified hardware/software troubleshooting including surveillance/access control. Partial mandatory units: fluent English; customer expectations and complex issue communication; the complete networking list; HTTP/HTTPS/TLS. Preferred units not confirmed: IT certification examples; ONVIF/VMS/streaming familiarity; KCS methodology; additional languages. CRM is confirmed separately from KCS.

Elapsed full trial, including local validation/save/exports: **56.21 s**. Provider metrics:

| Call | Prompt tokens | Completion tokens | Provider time |
|---|---:|---:|---:|
| Analysis | 3,903 | 481 | 11.88 s |
| Resume | 3,902 | 2,024 | 41.70 s |
| Total | 7,805 | 2,505 | 53.58 s |

Total reported tokens: **10,310**. A later deterministic revalidation after coverage/example refinements confirmed unchanged counts, score and completeness; it did not call any AI provider.

## Validation and limitations

Targeted tests cover section classification, alternatives/examples, CRM/KCS, B2, explicit absence, incomplete coverage, counters, first-export selection, per-CV persistence, CSRF/strict IDs, legacy/photo preferences, presentation-only edit preservation, real PDF/DOCX full-content retention, existing matching regressions, provider routing, storage and resume workflow. 81 targeted tests passed in 19.71 s. Ruff and `git diff --check` pass.

Playwright checked eleven authenticated main views at both 1440×1000 and 390×844, plus login and the demo login prefix. Controls were English, selectors available in analysis/preview/edit, no horizontal document overflow and no JavaScript errors. Screenshots were inspected for desktop analysis and mobile preview. PDF pages and LibreOffice-rendered DOCX were inspected; summary, all experience bullets, all projects and interests survive both theme exports. Both DOCX files contain identical paragraphs. Verification screenshots and raw private artifacts remain outside the repository.

PDF themes keep their existing visual design. Long resumes may occupy multiple pages; this preserves text. DOCX uses the existing simplified document flow and does not reproduce the PDF sidebar; the interface explicitly states this. Section recognition and evidence matching remain conservative, and unfamiliar source layouts can require review. New English prompts govern generated explanations, while verbatim source quotes and proper names retain their original language. Legacy reasoning is preserved, not retroactively translated. Existing Jinja/Starlette deprecation warnings remain non-failing.

The pre-work snapshot was committed and pushed as `deb4820`. The final change is committed and pushed separately. Login, license, configured model names, connection settings, private profile and skills bank were not modified.
