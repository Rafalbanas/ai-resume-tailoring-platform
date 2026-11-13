# Small, source-grounded resume refinements

## Diagnosis and scope

The existing pipeline already ranks retrieved facts, validates source ownership,
preserves proficiency, reviews summaries, de-duplicates bullets and selects complete
project sentences. No additional model stage is needed. Review covered
`ai_provider`, `role_focus`, `professional_summary`, `fact_retrieval`,
`content_quality`, `one_page_resume`, `ollama_draft_review`, `fact_validator`,
Skills Bank and the existing quality/export regression suites.

The changes address specific gaps:

- DevOps/SRE/platform/infrastructure and system-administration titles previously
  fell through to `other`. Limited title-only families now rank existing facts.
  Incidental words in the posting do not reclassify a support title.
- A fallback identity sentence consumed the first employment fact's ID without
  displaying its technical content. That duty now remains available for selection.
- Equally relevant employment is no longer displaced merely because another fact
  belongs to a project. Current duties use separate complete source sentences
  rather than inconsistent semicolon lists outside the compact support composition.
  More known action verbs can be safely
  inflected under background/previous-role/project scope introductions.
- Valid model bullets now receive relevance ordering even without analysis
  priorities. Analysis evidence retains precedence; ties retain input order.
  The slider's source-order endpoint and manual bullet ordering remain intact.
- Relevant Basic skills remain; unrelated Basic fillers are skipped when selected
  relevant practical skills already provide stronger evidence. The existing soft
  ten-skill target otherwise remains compatible, with at most sixteen bank skills.
- Prompt guidance emphasizes coherent summaries, scope-aware tense and relevance
  instead of filling a numerical skills quota.

Retrieval, fact eligibility, optional Ollama review, one-page omission policy and
export implementations are not changed. No match-score thresholds are changed.

## A broader headline without a new occupation

The actual current occupation is a safe default, not the only presentation.
In addition to the existing optional pipe suffix, the validator accepts two whole
source labels joined by ` & `, ` / `, ` — `, ` · ` or ` | `:

- actual current occupation plus an eligible selected skill, in either order;
- two eligible selected skill wordings, describing a capability-focused profile.

For example, **only when `IT Infrastructure` is itself eligible wording**:

> Before: Technical Support Engineer (L2)
>
> After: IT Infrastructure & Technical Support Engineer (L2)

This is profile presentation, not a replacement employment title. No new schema,
headline setting, automatic title upgrade or semantic permission is introduced.
Every component is checked after Skills Bank selection, including Basic/Junior
qualifiers. Unsupported tools, stripped levels and invented occupations revert to
the safe existing headline. Whole labels share the existing 64-character budget;
an actual occupation that already exceeds it is preserved by the existing fallback.
Manually retained broader headlines undergo the same source checks.

This deliberately does not accept arbitrary generated occupational synonyms.
A descriptor found only in project prose, but not in eligible skill wording,
does not become an unverified professional title.

## Deterministic Before / After

The fictional profiles in `tests/test_resume_editorial_scenarios.py` cover:

| Case | Before | After |
| --- | --- | --- |
| A: Technical Support → DevOps | Customer-request documentation is the first bullet. | Bash/Linux service automation is first; Linux monitoring and log investigation remain visible. |
| B: IT Administrator → System Administrator | Equipment inventory is first; summary duties are joined with `; Tested ...`. | Windows/Active Directory administration is first; completed backup testing remains a separate past-tense sentence. |
| C: Application Support → Production Support | Customer-request documentation is first. | SQL/API/log troubleshooting is first; the existing compact, scope-separated support summary is retained. |
| D: Limited employment → Software Engineer | Python API and pytest work is explicitly a personal project. | That correct boundary is retained; no artificial change or commercial-experience upgrade. |

Actual fallback output for B:

**Before**

> IT Administrator at Example Operations. Administers Windows servers and Active Directory; Tested backup restoration for Windows servers.

**After**

> IT Administrator at Example Operations. Administers Windows servers and Active Directory. Tested backup restoration for Windows servers.

An additional single-duty regression verifies that `Automates Linux service checks
using Bash.` no longer disappears after its ID is used to introduce the occupation.
An administration-background regression verifies:

> Background: Administers Linux services in a personal lab.

becomes:

> Broader experience includes administering Linux services in a personal lab.

Skills example: verified practical Linux and Basic Docker remain `Linux`,
`Basic Docker`; unrelated Basic photo-editing/macros do not pad this list.
Manual selection still retains an eligible Basic skill explicitly chosen by the owner.

The comparison was performed locally against the pre-change `HEAD` service code
and the changed code using the same synthetic fixtures, without provider calls.
It is a deterministic presentation comparison, not a measured improvement in hiring
probability, semantic match score or live model output.

## Validation and limitations

Validation results (local, without paid AI calls):

- Final rerun of editorial scenarios, broader headlines, infrastructure families
  and the entire export-quality module: **86 passed**, including actual synthetic
  HTML/PDF/DOCX exports.
- Additional quality/source-scope/recovery regression group: **328 passed**.
- Manual Truth Lock, safe edits, Custom CV, re-tailoring, source scope and learning
  regression group: **185 passed**. These groups overlap; do not sum the counts.
- `ruff check app tests scripts`, `git diff --check` and the read-only README
  synchronization check passed.
- The full suite, started before the final fixes, reported **2509 passed,
  1 skipped, 3 failed** in 45 minutes. Its failures were confined to
  `test_resume_export_quality`: an overlong support summary and two obsolete
  ten-skill-padding expectations. The support composition was corrected and
  export tests now check both short relevant lists and ten relevant Basic skills.
  The final 86-test rerun above includes the complete corrected module.
  The entire full suite was not rerun a second time on the final snapshot.
- Repository-wide `ruff check .` additionally found 50 pre-existing issues in
  the untracked `artifacts/emfire-demo/scripts` directory, outside this change.

Focused checks:

```sh
.venv/bin/pytest -q tests/test_resume_editorial_scenarios.py \
  tests/test_profile_headline.py tests/test_infrastructure_role_focus.py \
  tests/test_headline_suffix_budget.py tests/test_skills_bank.py \
  tests/test_role_focused_summary.py tests/test_summary_scope_composition.py \
  tests/test_tailoring_priorities.py tests/test_fact_validator.py \
  tests/test_custom_cv.py tests/test_manual_truth_lock.py \
  tests/test_fact_retrieval.py tests/test_ollama_draft_review.py \
  tests/test_gemini_provider.py tests/test_ollama_provider.py \
  tests/test_resume_export_quality.py tests/test_html_resume.py
.venv/bin/ruff check app tests scripts
.venv/bin/pytest -q
```

The fallback intentionally remains conservative: sparse facts may yield fewer than
three sentences, unknown/negated/planned syntax may retain a neutral scope label,
and a sole relevant fact may recur in Summary and Experience. Do not invent or
discard useful evidence solely to force four sentences or zero overlap. Source
grammar is not universally rewritten; this is not a general English grammar engine.
The new families are bounded lexical ranking, not semantic proof of expertise.
Natural 3–4-sentence paraphrases remain the responsibility of the existing model
and review flow, with the source-bound fallback on rejection.

Saved CVs, production profiles, manual skill membership, providers, recovery,
source IDs and provenance remain unchanged. PDF/DOCX/HTML use existing templates.
No dependency, migration, extra routine AI call or deployment is required.
