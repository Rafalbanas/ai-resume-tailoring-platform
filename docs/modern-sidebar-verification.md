# Modern Sidebar pagination verification — 2026-10-11

The fix retains Modern Sidebar, its colours, portrait, hierarchy and 61 mm sidebar. It does not reduce the 8.7 pt body font or remove substantive CV facts. The browser preview now displays the actual WeasyPrint PDF pages, with accessible extracted text, PDF link overlays and a portrait control aligned to the rendered portrait. PDF exports remain searchable vector text. This adds the pinned BSD/Apache-licensed PDFium renderer `pypdfium2==4.30.0` for preview images; installing updated requirements is necessary when deploying.

## Checked state and document

- Initial worktree was clean; repository HEAD and running container build were both `d49f40cffe614b9a8a20113768b667d3f0f25655`.
- Running container: `cv-tailor`, build timestamp `2026-10-11T10:53:49Z`, local port 18000; public authenticated preview was inspected read-only.
- Latest application ID: `2026-10-11_reply-polska-sp-z-o-o_customer-service-consultant-microsoft-dynamics-365_4`.
- Four matching applications were found. Their creation times, derived from immutable `resume.generated.json` timestamps and cross-checked against history/draft data, were 09:17:52, 10:03:28, 10:03:31 and 11:16:03 UTC. The latest draft ID is `e234bd95bc5d480d94545c57a42fe06a`; its exports were written at 11:18:02–03 UTC.
- Current saved theme was ATS Classic, not Modern Sidebar. Its existing PDF has two pages. No stored Modern PDF for this particular version was present, so the Modern baseline was reconstructed using exactly the same saved resume, profile/photo, empty layout guide and original generator/CSS. Other application versions were not substituted for this CV.
- Saved `resume.json`, generated baseline and pre-fit snapshot contain the same duplicated summary. The original saved AI response contains only one partner-support sentence. The duplicate was introduced by Truth Lock's deterministic `build_summary`, which selected the summary identity and a more detailed experience sentence about the same fact.

## Confirmed causes and changes

The HTML preview used a fixed 297 mm card and ordinary browser flow. Browsers do not implement WeasyPrint's running footer or print page breaks, so consent appeared above the card and the Linux project/technologies extended below it. PDF was already keeping consent in a reserved margin. Modern's generous gaps, whole-entry break avoidance and lack of continuation furniture left the last two projects on a sparse second page.

`static/resume.css` now tightens Modern-only gaps, permits entry fragmentation, keeps headings with subsequent content, wraps long titles/dates/identifiers and repeats sidebar colour plus candidate/page identification on continuation pages. It reserves the original consent margin. ATS typography and pagination rules are retained.

`PDFGenerator.render_preview` uses pages produced from the same HTML/CSS and WeasyPrint renderer as PDF export. It rasterizes only the browser representation, preserves clickable PDF hyperlinks and accessible text, and leaves photo management available. The route calls this paginated preview instead of letting the browser reflow print HTML. Responsive page frames replace the fixed-height preview card.

`deduplicate_summary` combines only verbatim verified source clauses, preserving the first sentence's employer/product identity, the technical-support qualifier and all additional issue-resolution details. It compares numbers and negation, leaves unknown/model paraphrases for existing fact validation and retains source IDs. It runs in summary rebuilding, after normal Truth Lock checks and on in-memory export copies so existing records are not rewritten. Neither the master profile nor the skills bank changes.

## Visual verification and page counts

All pages of the original/latest PDF and control PDFs were rasterized and viewed. Browser inspection included the authenticated existing production preview, both baseline HTML themes, both corrected themes through the actual preview route on a temporary read-only loopback server, all synthetic paginated previews, a 390 px mobile viewport, PDF link overlays and opening photo controls. Final inspection corrected the portrait overlay to use the rendered border-box coordinates, preventing a duplicate shifted portrait.

| Saved or synthetic case | Modern before → after | ATS before → after |
| --- | --- | --- |
| Latest Reply CV | 2 → 1 | 2 → 2 |
| Short fictional CV | 1 → 1 | 1 → 1 |
| Long fictional CV: long titles, links, technologies, 18 lengthy skills | 4 → 3 | 4 → 4 |
| Same long CV with a shorter skills panel | 4 → 3 | 4 → 4 |

The corrected current Modern page includes all three projects, their complete descriptions and technology lists and the consent clause. Both ATS pages retain complete content and consent. Long Modern documents split entries and the skills list safely across pages, repeat the coloured sidebar and include continuation identification. All inspected corrected pages have content, with no clipping, footer collisions, hidden text, empty pages or consent-only pages. Geometry checks cover paper boundaries and the reserved footer area; a regression test compares preview page pixels against PDF-rendered pixels.

DOCX controls were opened/exported by LibreOffice and every page inspected: current CV two pages for either theme, short CV one page, long variants four pages. Comparing baseline and corrected current DOCX ZIP members confirms identical content/formatting/media except the deliberately deduplicated summary and optional core timestamp. DOCX remains the existing simplified layout.

## Checks and data preservation

- Targeted pagination, PDF, theme persistence, portrait workflow and fact-validation suite: **21 passed**.
- Full suite: **238 passed, 6 failed**. All six failures reproduce on an isolated, unmodified checkout of `d49f40c`; baseline affected modules: **21 passed, the same 6 failed**. These concern existing qualification assessment expectations and interests fixtures/legacy overflow expectations, not new export regressions.
- The six pre-existing failures: `test_mandatory_gap_overrides_many_easy_matches`, `test_model_cannot_add_requirement_or_prompt_instruction`, `test_full_requirements_heading_and_partial_preference`, `test_interests_candidate_profile_routes`, `test_interests_rendered_in_sidebar_and_excluded_from_ats`, `test_interests_removed_first_on_overflow`.
- Ruff checks for application code and modified/new tests: passed. `git diff --check`: passed.
- Photo test fixture was given the provider/demo state now required by the existing page context; runtime provider behaviour was not changed.
- SHA-256 comparison of **193 original files**, including all saved application artifacts, master profile and skills bank: unchanged.
- No model, job-analysis or provider calls were performed. No application CV, history, profile or skill data was overwritten. Control files and screenshots are separate in `data/.diagnostics/sidebar-fix/` (ignored private artifacts). The verification scripts, page images, browser screenshots, `results.json` and preservation hashes are retained there.
- No revert was needed: there is no demonstrated new export regression. Temporary discarded implementation experiments were never committed.
- Changes are committed in the repository only. The production container was not rebuilt/restarted or deployed, and its historical export files remain unchanged.

## Changed files

- `app/routes/web.py`
- `app/services/pdf_generator.py`
- `app/services/docx_generator.py`
- `app/services/professional_summary.py`
- `app/services/fact_validator.py`
- `static/resume.css`
- `static/app.css`
- `requirements.txt`
- `tests/test_sidebar_pagination.py`
- `tests/test_quick_profile_photo.py`
- This verification report.
