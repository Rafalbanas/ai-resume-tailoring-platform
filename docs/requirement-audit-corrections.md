# Requirement audit corrections

These changes address reproducible source/classification/evidence failures without
changing private profiles, SkillsBank data, existing reports or generated exports.
They apply to newly validated analyses with either lexical or hybrid retrieval.
There are no new dependencies, model calls, configuration flags or migrations.

## Corrected boundaries

* **Heading recognition:** standalone `⭐ Mile widziane`, its variation-selector
  form and `✨ Mile widziane` reset priority to preferred. `Experience required`
  and `Wymagane doświadczenie` reset to mandatory and remain context headings,
  not candidate qualifications. Technical punctuation, numbers and levels remain.
* **Explicit capabilities:** Polish ability/knowledge clauses and English language
  proficiency are assessment-bearing. A complete LLM response cannot hide them as
  responsibilities or context and still claim reliable coverage. Existing bounded
  provider recovery requests the missing assessment; the validator does not invent
  a replacement qualification or candidate evidence.
* **Whole-condition validation:** SQL/API use does not establish Postman. An omitted
  named Postman AND component is restored for independent assessment. Source scope
  ceilings run in semantic and parser-backed paths, including after component/date
  arithmetic. CI/API regression tests alone do not establish automated LLM
  evaluation tools or prompt-regression testing. OR and illustrative examples keep
  their previous semantics.
* **Proficiency:** explicit advanced/very-good Python and ML requirements need an
  appropriate advanced attestation or eligible advanced bank skill. Intermediate,
  academic or ordinary practical use cannot by itself confirm that level. The
  guard is intentionally narrow, not a new general competence classifier. It
  preserves qualifying advanced evidence and does not manufacture a confirmed gap.
* **Specialist tenure:** software-testing minimum years require dated testing
  activity, not unrelated technical-support/SQL duties. A support title does not
  prevent valid testing duties from counting. Existing overlap/date handling and
  the stricter explicit pentesting scope remain in force.
* **PL/EN repetition:** explicit, bounded bilingual contract vocabulary identifies
  equivalent testing/evaluation requirements. Matching rows share one assessment
  while retaining every literal source quote. Conflicting statuses use the
  conservative result and require interpretation review. Unknown substantive
  words, product names, levels, negations and logical conditions cannot disappear
  from the fingerprint. Complex multiple-number contracts are not merged. All
  source quotes survive revalidation and count toward source coverage.

## Limitations and compatibility

This is not an arbitrary translation engine. Unrecognized translations or
ambiguous compound conditions may still need model/human review rather than
automatic deduplication. A result requiring source/evidence recovery remains
unreliable instead of being assigned a more flattering qualification score.
Existing stored reports do not silently change. Reanalyse their original offers
after deploying the correction if a new report is desired; old CVs and private
candidate evidence remain untouched.

## Verification

All regression fixtures are fictional. Private audit documents were not copied
into the repository and no private candidate data was sent to external model APIs.
An initial 11-case reproduction produced **7 failures and 4 passes** before fixes.
The expanded new suites subsequently passed **45 tests**. A focused integration
run also passed **229 tests** covering the new cases and existing source scopes,
evidence matching, LLM-first interpretation, source dispositions, token budgets and
indexed recovery. These runs overlap and are not added together as a benchmark.

```sh
python -m pytest -q tests/test_audited_matching_accuracy.py tests/test_decorated_qualification_headings.py
python -m pytest -q --tb=short
python -m ruff check .
python scripts/check_environment.py --dev
python -m pip check
git diff --check
```

Tests use the isolated Python 3.14 environment matching pinned project dependencies.
The final full suite was run alone and completed with **2047 passed, 1 skipped,
13 warnings in 1442.65 seconds (24:02)**. The skipped test requires an explicitly
configured real local embedding model; the warnings are third-party LangSmith
deprecations (pytest-asyncio also warns about its unset future fixture-loop default).
Ruff, dependency consistency, environment conformity and diff checks passed.
These are results for this correction branch, not the earlier hybrid feature run.
No production documents or reports were rewritten, and no service was deployed.
