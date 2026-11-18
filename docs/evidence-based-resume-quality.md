# Evidence-based resume quality

## Audit: baseline `32d28d6`

The baseline already contains the richer generation and export fixes from
PRs #124 and #125. This audit starts after those fixes, not from the local
working directory or an older deployed version.

| Pipeline stage | Finding |
|---|---|
| Profile, Skills Bank, fact catalog | The profile owns the approved text and employment dates. The bank adds eligibility, scope and level constraints. The CV catalog can exclude a fact for a particular offer. There is no reason to edit the profile to improve a generated CV. |
| Job parsing and assessment | `job_sections` and `AnalysisValidator` already distinguish duties, requirements and context. Responsibilities do not create qualification blockers, but the deterministic CV ranker consumed mostly the title and token overlap, not that structure. |
| Retrieval and skills | Mandatory queries are weighted in BM25 (or optional local hybrid search); when requirements exist, a duty can disappear from queries. The skill panel and project scoring also reused title-only categories. |
| Draft and summary | The LLM is prompted to be specific, but a supported, generic draft receives no consistent penalty. The support fallback can prioritize the same SQL/log/English/Python patterns for different jobs. A terse but reviewed paraphrase can omit the scale of the fact it cites. |
| Truth Lock and editorial quality | Facts are owner-scoped; unreviewed prose must match permitted source text or existing deterministic transformations. Reviewed paraphrases have server attestations, and final summary confirmation is separate. Existing checks address duplicate text, dangling fragments and proficiency, not whether a key supported detail made it into the CV. |
| Pagination and rendering | `prefer_one_page` checks real A4 geometry and protects mandatory evidence, but candidate scale/results can be deleted if the analysis did not cite them. PDF and offline HTML share paginated rendering; DOCX has its own flow. The legacy explicit hard-fit mode and manually edited exports have separate policies. |

## Design

- Share an advisory role focus across selection stages. Give precedence to
  duties and required skills, retain overlapping role families, and exclude
  recognized benefits and recruiting context from focus. Do not feed the
  resulting scores into qualification assessment.
- Rank documented activity, scope and results within the same role theme.
  Prefer concrete recorded clauses to generic duty shells. A scope statement
  such as “170 users across five locations” remains scope, not a claim about
  uptime, cost savings or productivity. Keep employment owners and titles.
- Keep the exact source wording available when the selected prose drops
  material scope or a measured result; do not ask another model to infer it.
  The existing allowlists, source checks, review and ownership boundaries
  remain in place. Projects remain separate from employment.
- Report likely generic duties, repetitive summaries, tool lists without
  activity, and omitted relevant scope/results as review hints, not export
  blockers. The draft report displays them separately from Truth Lock
  warnings. Do not require numbers or a minimum amount of text for sparse
  profiles. For postings whose duties are too vague to narrow project
  selection, retain the existing project slots and ranking.
- Protect relevant scope/results in the normal one-page preference. If
  removing optional details is insufficient, keep the complete validated CV
  and paginate. There is no two-page hard limit for unusually long profiles.

## Before and after

| Offer | Target employment facts retained | Bullet repetitions in summary | Expected project retained |
|---|---:|---:|---|
| Technical Support Engineer | 1/1 → 1/1 | 3 → 2 | Not required |
| Windows Administrator | 2/2 → 2/2 | 3 → 1 | Not required |
| Production Support Engineer | 2/2 → 2/2 | 4 → 1 | Not required |
| Technical Implementation Specialist | 2/2 → 2/2 | 3 → 1 | Personal calendar connector, first in both |
| Junior DevOps Engineer | 3/3 → 3/3 | 3 → 1 | Personal container lab, first in both |

- The five ATS Classic CVs all remained one page. Exact generic fixture bullets
  went from **8 to 0**. Total employment source bullets fell from **30 to 21**
  and displayed project entries from **10 to 2**. This is reduced breadth,
  not increased evidence coverage. The 170-user/five-location fact and the
  DevOps timing result remained visible in their respective target CVs.
- Overlap of bullets from the most recent job fell from **0.145 to 0.033**.
  Overlap across **all** employment increased from **0.282 to 0.341**: the
  earlier support role's useful history was largely shared. The evidence for
  differentiation is therefore limited to the most recent role on this fixture.
- The longer ATS Classic fixture kept **15/24 → 24/24** scoped bullets by
  using **1 → 2** pages. Modern Sidebar kept **24/24** on one page in both
  versions of this fixture. All checked fields were extractable in PDF, DOCX
  and offline HTML in all five cases and both stress-test themes.
- No benchmark owner/citation errors or offer-only Kubernetes/Terraform
  claims were detected. Separate regression tests inject unsupported metrics,
  titles and project evidence into draft employment to exercise Truth Lock.
- One local `gemma4:12b-it-q4_K_M` implementation-role smoke preserved **2/2**
  facts, a separate personal project and all **22/22** checked text fragments
  in each format. This is a single run; it does not measure reliability or
  comparative model performance. Spot checks included a PDF render, a
  LibreOffice DOCX render and offline HTML opened in Chromium.

For example, the implementation fallback previously repeated both the
OAuth diagnosis and the SSO onboarding statement in the summary and work
history. It now highlights the OAuth diagnosis in the summary, keeps both
specific duties in Experience, and leaves the personal calendar integration
under Projects. These are original documented facts, not invented outcomes.

## Reproduction

From the feature worktree, using the same Python 3.14 environment on both
revisions:

```bash
FEATURE="$PWD"
git worktree add --detach /tmp/cvtailor-quality-baseline 32d28d6
(
  cd /tmp/cvtailor-quality-baseline
  PYTHONPATH="$PWD:$FEATURE" python "$FEATURE/scripts/compare_resume_quality.py" \
    --exports --rich-layout --output /tmp/cvtailor-quality-before
)
PYTHONPATH=. python scripts/compare_resume_quality.py \
  --exports --rich-layout --output /tmp/cvtailor-quality-after
pytest -q tests/test_evidence_based_resume_quality.py
```

The benchmark uses the source parser, the same deliberately sparse draft,
and the same offer and evidence in both revisions at `tailoring_level=0.5`.
It counts exact annotated target facts in employment (not keywords or
qualification grades), then checks which are retained after fitting. The
mean pairwise Jaccard is the intersection/union of rendered experience
bullet sets, reported for all jobs as well as the most recent job. Common
legacy employment can increase the overall ratio when generic bullets are
removed. Lower isn't necessarily better: different wording or dropping good
shared evidence could also decrease it. Results and exports go outside the repo.
Automated extraction tests are not a substitute for recruiter review.
This benchmark uses the production renderers in-process to isolate output
quality from subprocess startup and time limits. Worker integration is covered
by the existing export/sandbox tests.

An optional already-installed loopback Ollama model can exercise the real
draft/review path on one offer with `--ollama-model MODEL --only 'ROLE'`.
The benchmark still uses parser-backed analysis so this is a draft and
review smoke test, not a test of semantic job analysis. It sends only the
fictional profile.

```bash
PYTHONPATH=. python scripts/compare_resume_quality.py --exports \
  --only 'Technical Implementation Specialist' --ollama-model gemma4:12b-it-q4_K_M \
  --output /tmp/cvtailor-quality-ollama
```

## Limits

- Role signals are lightweight English-oriented heuristics. They can miss
  unusual vocabulary, unstructured postings and multilingual variants; they
  do not replace validated requirement analysis.
- Editorial signals are not grammar or semantic entailment models. They
  detect some clichés and near-verbatim repetitions, not all redundant
  paraphrases or awkward sentences. A repeated detail can be justified.
- This is a small benchmark on one synthetic career and a separate layout
  stress profile, not a representative sample of recruiter decisions.
  Extracting the same text from the exported files does not prove compatibility
  with every ATS or that all Word processors paginate a DOCX identically.
