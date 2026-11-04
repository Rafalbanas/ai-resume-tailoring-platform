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

Source-composed summaries explicitly label project facts, for example:

> Support Engineer at Example Ltd. Project work: Integrated local models into a
> FastAPI application.

The neutral label comes from the fact's project provenance, not from the job ad.
It prevents an employer introduction from making project work appear to be a
duty performed for that employer. No target occupation, invented achievement or
new metric is added. A reviewed model summary citing project facts without
project scope falls back to this source-composed form; a genuinely scoped natural
summary still retains its exact-text owner-confirmation requirement.

Projects are ranked by source-backed relevance to the supplied role/offer before
secondary model-evidence priority. An unrelated citation should not put a less
relevant academic project ahead of a more relevant backend/API project. Project
selection remains lexical and locally computed, not a semantic-quality guarantee.

The same factual validation, competence levels, summary signatures, mandatory
review and PDF/DOCX layout/export checks remain in effect. These guards run
locally and introduce no separate AI stage; existing batching, retry/recovery
and summary-review policies still apply. No new provider, dependency, environment
variable or storage migration is introduced. Latency/token savings are not claimed.

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
  tests/test_tailoring_priorities.py tests/test_summary_confirmation.py
```

The fixtures use fictional employers, profiles and offers. They cover known
headings, hidden/downgraded minimums, specialist employment versus general support,
valid specialist evidence, summary provenance/signatures/confirmation and project
ordering. No private CVs or live/paid AI calls are needed for these tests.
