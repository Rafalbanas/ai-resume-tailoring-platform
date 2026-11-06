# Source-grounded CV quality guards

New analyses and drafts include deterministic checks for several common quality
failures. They complement the model and Truth Lock; they do not establish hiring
probability, universal ATS compatibility, or complete understanding of every offer.

## Offer analysis

- Natural Polish/English headings such as “Jakie kompetencje są dla nas ważne?”
  and “To qualify for the role, you must have” delimit qualifications separately
  from duties, benefits and optional requirements.
- Literal English/Polish minimum-tenure clauses, including numeric ranges and
  `min.` / `co najmniej`, cannot be silently classified as context. An incomplete
  disposition map remains `UNRELIABLE / RETRY`, not a high-confidence match.
- Explicit Polish candidate predicates such as `Masz doświadczenie ... minimum
  5 lat`, `Posiadasz praktyczne doświadczenie`, `Znasz` and `Posługujesz się
  językiem ... B2` remain candidate conditions even if a model calls them duties.
  Their source priority and literal minimum years are checked independently.
- Polish prose headings for qualifications, duties, recruitment and contact
  information delimit their own sections. Known headings and administrative
  passages are retained as context, not scored as preferred qualifications, even
  in a complete model disposition map. Genuine candidate conditions override an
  inherited administrative section; these checks are not a universal classifier.
  Sparse legacy responses retain the existing fail-closed classification audit
  when qualification-bearing words were extracted from administrative context.
- Identical repeated qualification passages with the same source metadata are
  assessed once. The full original offer and occurrence inventory remain intact.
  Distinct priorities, levels and AND children are not merged. Priority words
  such as `optional` in a model's level field do not create a new proficiency
  distinction or duplicate score. Conflicting interpretations still need review.
- Model priorities are checked against the original source, independently of the
  model's own disposition map. A clear minimum in a mandatory section cannot
  become merely preferred. Genuine preferred qualifications remain optional.
- Named pentesting, data-engineering and cybersecurity tenure uses explicit
  relevant employment duties. General support, SQL troubleshooting, titles,
  undated projects or coursework alone do not establish years in those specialist
  scopes. These are conservative domain ceilings, not an exhaustive profession
  classifier; other roles retain the existing cited-evidence interpretation.
- If mandatory tenure is not fully established, the recommendation requests
  `REVIEW` rather than suggesting a reasonable stretch solely from unrelated
  matches. This means “verify the evidence”, not “the candidate cannot do it”.

Dates, overlap handling, language levels, AND/OR constraints and source quotation
checks remain active. Missing evidence is not automatically treated as a proven
absence of competence. Model refusals/conflicting interpretations stay visible.

## Generated CV content

Source-composed summaries use active natural wording for a small allowlist of known
initial verbs, for example:

> Support Engineer at Example Ltd. Project work includes integrating local models
> into a FastAPI application.

Other phrases like 'Previous roles involved using...' or 'Broader experience includes
automating...' are permitted. Unknown, planned, or negated clauses retain verbatim
neutral labels. No new facts/results are added; exact citations and the
700-character bound are preserved.

Activity wording inflects a known coordinated initial verb chain together:
`Built and tested ...` becomes `building and testing ...`, not `building and
tested ...`. Ambiguous coordination after an object, unknown verbs and qualified
clauses retain the complete original wording under a neutral scope label.
The old first-verb-only transformation of a cited source clause cannot be waived
by a model summary signature. This is not a general English grammar checker.

Projects are ranked by source-backed relevance to the supplied role/offer before
secondary model-evidence priority. An unrelated citation should not put a less
relevant academic project ahead of a more relevant backend/API project. Project
descriptions prefer another relevant verified fact rather than copying a complete
summary clause, only if an alternative exists; otherwise, the sole fact
remains and the manual-preserve path is unchanged. Selection remains lexical
and locally computed using exact/activity clause comparison, not fuzzy/semantic
deduplication.

Project cleanup also handles a bounded nominal/action repetition such as
“comparison of multiple machine learning models” followed by “Evaluated multiple
machine learning models as part of the MSc thesis”. It keeps the literal thesis
scope in the combined description. Different methods, metrics, objects, negation,
plans and proficiency/scope qualifiers are not treated as equivalent evidence.
The same cleanup runs at factual validation and PDF/DOCX preparation.

Generated project descriptions select at most two complete verified source
sentences, normally within 500 characters, instead of concatenating two whole
multi-sentence paragraphs. A sole long source sentence stays complete rather
than being clipped. The manual-preserve path does not shorten an owner's
paragraph, and no source facts or saved documents are rewritten.

The same factual validation, competence levels, summary signatures, mandatory
review and PDF/DOCX layout/export checks remain in effect. These guards run
locally without a new routine AI stage; existing batching, retry/recovery
and summary-review policies still apply. No new provider, dependency, environment
variable or storage migration is introduced. Latency/token savings are not claimed.

Deterministic summaries keep one explicit scope block for projects, separate from
older employment and global background. The neutral colon labels are retained only
when a clause cannot be safely inflected.
Summaries naming the current employer but citing earlier duties without
explicit previous-role wording or the former employer fall back to source-composed
text, even if signed by the model. This is a conservative, bounded heuristic,
not complete semantic entailment.

The terminology guard catches obvious library-as-model lists and predicates for
scikit-learn/sklearn, NumPy and pandas. Legitimate wording such as “trained
scikit-learn models” or “using scikit-learn” remains allowed; XGBoost is not
automatically rejected. All visible export text is checked before PDF/DOCX
workers. Bad source wording is not automatically corrected and may block export
pending source review.

## Error handling and limits

- Ollama final source-classification errors map literal quotes from completeness/
  classification/evidence errors to all affected occurrence IDs. Only these
  passages are retried within the existing shared analysis_recovery_calls budget. Titles,
  tags, and duties are not forced into candidate qualifications. Conflicts
  still fail closed if the model cannot reconcile; the system does not
  automatically choose a category.
- CV output_limit gets one fresh concise same-model same-output-budget retry,
  preserving full evidence/employment/education ownership. No partial JSON is
  accepted, and no retries are performed for context, HTTP, auth, or
  invalid JSON failures. The bounded retry schema reduces optional detail with no
  budget increase. This adds a call only when CV length limit occurs;
  no new routine AI stage is introduced.

## Existing documents and use

Existing CVs, saved PDFs/DOCX, profiles and historical match reports are **not**
rewritten by this change. Run a fresh analysis to use the new interpretation
guards. Explicit reuse of a saved analysis revalidates it; incomplete old reports
may now require fresh analysis instead of generating another draft.

Review the original posting and unresolved mandatory conditions before applying.
Do not change your documented job title to a target title or invent numbers to
make a draft look stronger. Keep academic/project work distinct from commercial
employment even when it demonstrates useful transferable skills.

## Regression checks

```sh
.venv/bin/pytest -q tests/test_cv_quality_guards.py \
  tests/test_source_qualification_guards.py tests/test_llm_first_analysis.py \
  tests/test_tailoring_priorities.py tests/test_summary_confirmation.py \
  tests/test_summary_scope_composition.py tests/test_ml_terminology.py \
  tests/test_cv_content_policy.py tests/test_ml_terminology_integration.py \
  tests/test_summary_editorial_quality.py tests/test_project_summary_repetition.py \
  tests/test_generation_recovery.py tests/test_source_disposition_regressions.py \
  tests/test_polish_source_headings.py tests/test_coordinated_summary.py \
  tests/test_project_editorial_cleanup.py
```

The fixtures use fictional employers, profiles and offers. They cover known
headings, hidden/downgraded minimums, specialist employment versus general support,
valid specialist evidence, summary provenance/signatures/confirmation and project
ordering. No private CVs or live/paid AI calls are needed for these tests.
## Conservative application recommendations

New analyses score distinct mandatory requirement groups, not repeated source
rows or preferred matches. `APPLY` requires every mandatory group to be fully
supported. `REASONABLE_STRETCH` requires at least one fully supported group,
a weighted evidence score of at least 0.4 (strong = 1, partial = 0.5), and fewer
than half the mandatory groups without supporting evidence. Otherwise the advice
is `REVIEW`, not a positive stretch recommendation. A confirmed mandatory gap
produces `SKIP`, even when other qualifications are strong. Missing evidence alone
does not establish inability. Existing uncertainty, specialist-tenure and source
reliability guards still apply.

These are conservative advice thresholds, not hiring probabilities. They do not
block an owner from exporting an otherwise valid CV, certify readiness to send,
or rewrite saved analyses and documents. `completed` in a batch still describes
successful document generation, not a recommendation to apply.
