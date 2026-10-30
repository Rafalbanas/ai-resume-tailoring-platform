# Custom CV / AI Editor

## Usage

Open **New match**, then choose **Custom CV / AI Editor**.

### Generate from the master profile

1. Choose **Use Master CV**, give the CV a name, and enter instructions in
   **What would you like to change?** No company, job URL or job description is required.
2. Choose an AI engine and click **Generate CV**.
3. Review the source-validated draft and summary, choose ATS Classic or Modern Sidebar,
   then **Accept and save CV**. PDF/DOCX exports use the existing generation pipeline.
4. Reopen it in **History**. Rename, manually edit, duplicate, export, or choose
   **New version / revise prompt**. A saved CV can also be selected in the main form.
   Regeneration creates a separate draft/version and never replaces the source CV.
5. For targeted edits, choose **AI edit sections in a new text copy**. This opens
   an independent text-based copy; the structured CV and master profile remain unchanged.

Custom instructions can specify emphasis, target role/industry, tone, summary, detail,
section order and excluded sections. Templates retain their header/contact layout;
Modern Sidebar keeps sidebar content in its sidebar. Unsupported qualifications
are not permission to add them. Master-based generation retains Truth Lock and
its existing source and summary-review safeguards.

### Paste or import an existing CV

1. Choose **Paste Existing CV**. Paste the entire plain-text CV, or optionally
   extract text from a PDF/DOCX using the existing isolated document processor.
   Pasted text takes precedence over an attached file. Click **Import CV**.
2. Review the editable current CV and detected sections. Correct extraction or
   heading issues manually and save before running AI. An exact pasted original
   (or extracted original for a file) stays recoverable.
3. Select only the sections the AI may edit. A recognized summary is selected by
   default; otherwise select the desired scope explicitly.
4. Enter instructions, for example: “Improve the Professional Summary. Keep
   factual meaning and every other section unchanged.” If adding new facts,
   explicitly attest them in **Confirmed factual additions**.
5. **Apply changes** opens the existing background-task progress screen. The
   current CV remains saved and unchanged while AI works.
6. Review the highlighted text comparison. **Accept changes** saves a version;
   **Discard proposal** retains the current version. If factual support is missing,
   the UI asks for clarification instead of accepting the proposed content.
7. Repeat on the latest accepted text. **Undo** restores the preceding accepted or
   manual version (up to 50 retained versions); **Restore pasted original** recovers
   the original. Manual edits, rename, duplicate, delete and PDF/DOCX export are
   available in the editor. The library is linked from the main form and History.

Only accepted/saved text is exported, never a pending proposal. Verify the exported
page count when requesting a one-page CV; plain-text editing does not guarantee
an exact page count. File extraction does not retain the source document's page
layout and does not perform OCR. Unknown section headings can be corrected in the
text editor. Text exports offer ATS and modern styling, not reconstruction of an
arbitrary imported Word/PDF layout.

## Factual and privacy boundaries

- Master-based generation uses the master profile, verified skills, retrieval,
  provider routing/fallback and existing Truth Lock; job analysis is skipped.
- Text editing receives only the current imported CV, selected sections, instructions
  and explicit factual additions. No master-profile facts are silently supplied.
- AI returns section replacements, not a replacement for the whole document.
  Server-side application rejects unselected/duplicate/unknown section IDs and new
  unsupported numbers. An additional AI review checks factual entailment and scope;
  failed review yields clarification, not automatic acceptance.
- AI verification is not a proof of truth. Review wording, skill levels, dates and
  qualifications before accepting; manual changes are user-authored, not verified.
- Gemini sends the current CV and instructions to Google's API. Ollama uses the
  configured Ollama service. Existing provider budgets, timeouts and task errors apply.
- New routes require the existing authenticated session and CSRF for mutations.
  PDF/DOCX imports/exports use the existing network-isolated worker, including
  split API/document deployments. Imported text is escaped, not rendered as HTML.

## Persistence and compatibility

- Structured generated CVs still live in `data/generated/`; their existing metadata
  gains `workflow`, `cv_name`, and `source_cv`. Older files default to job mode.
  Drafts and task records use the existing stores. No migration is required.
- Imported text CVs live in account-scoped `data/custom_cvs/<uuid>.json`.
  Each document contains immutable original text, current accepted text, revision,
  bounded previous versions, and at most one pending proposal. Writes are atomic
  and locked; stale edits or delayed AI results cannot overwrite a newer revision.
- Neither workflow writes the master profile. They use existing backup/data-directory
  persistence. No new dependencies or automatic production migration/deployment.
- Section AI editing supports the existing Ollama and Gemini integrations. Providers
  without this capability return an actionable error; mock mode is not a real AI editor.

## Validation

```bash
ruff check app tests
pytest -q tests/test_custom_cv.py tests/test_custom_cv_storage.py tests/test_text_cv_export.py
pytest -q
python scripts/check_environment.py --dev
python -m pip check
```

Tests use fictional profiles and mocked AI. Live quality checks require an available
configured provider; automated tests do not send private CVs to real models.
