# Final source/scope integrity follow-up

Follow-up to the batch coverage correction in PR #103. The second read-only batch
audit found residual classification errors and a whole-condition confirmation
based only on one neighboring identity-security facet.

## Boundaries enforced

* **Whole-source ceilings:** Microsoft Entra ID (including Azure AD aliases),
  Conditional Access and MFA remain independent scopes. Short model labels,
  partial component lists and later aggregate calculations cannot use generic
  MFA configuration to confirm the complete identity condition. Direct matching
  and final source validation share these checks. Pure OR alternatives still
  need one valid branch; unresolved mixed AND/OR scopes require component review
  rather than treating a missing alternative as confirmed absence.
  Practical identity evidence binds the activity to the product; a neighboring
  service owned by another team, a planned activity or a negated action is not
  treated as completed product work.
* **Explanation consistency:** a remaining explicit evidence denial cannot
  coexist with full confirmation. Such contradictions are downgraded and flagged
  for review, without inventing a lack of candidate competence. An independent
  deterministic matcher can still replace a stale model explanation with actual
  supported evidence first.
* **Source dispositions:** offered compensation is employer context, not a
  candidate salary expectation. Explicit candidate mandates inside mixed
  compensation paragraphs remain assessment-bearing. Nominal ability,
  relationship/stakeholder, certificate and communication clauses are checked
  independently of a model's context/duty disposition. Leading Polish
  `Dużym plusem będzie ...` stays preferred.
* **Headings:** strict `Technical Capabilities` variants are qualification
  headings, never positive candidate qualifications. Sentences containing those
  words remain available for assessment.
* **Credentials and continuations:** product use, training, expired credentials,
  explicit non-possession and unrelated credentials do not prove a requested
  certificate. A model assessment of only an open `candidate must ...:` clause
  cannot claim complete coverage without verifiable continuation quotes. Complex
  or unresolved lists may fail closed for explicit recovery/review; they are not
  silently rewritten into a different set of AND/OR requirements.
  Possession and the credential name must occur in the same attestation clause:
  an ITIL credential does not validate a separate mention of CISSP training.
  Explicit credential conjunctions need every named credential. A family label
  cannot replace its specific listed identifiers; unresolved vendor-only scope
  remains a review case rather than a confirmed credential.

These are literal/factual safeguards, not a general semantic proof system.
Unknown products, paraphrases, complex nested lists and unfamiliar headings can
still require review. Passing tests is not a guarantee that every generated CV
or report is semantically correct.

## Validation

All regression candidates are fictional. Providers are mocked; no production
profile is used as a test fixture and no private candidate data is sent to model
providers. The initial valid 51-case source/scope regression file against an
isolated archive of `e347d92` produced **47 failures and 4 passes**. Additional
positive/negative credential and OR cases were then added. This is targeted
regression reproduction, not a general accuracy benchmark.

The reviewed focused run passes **661 tests**, covering three new files and existing
source coverage, identity/evidence scopes, language/tenure contracts, token
budgets, indexed recovery and graph orchestration. Ruff and diff checks pass.
Additional adversarial review reproduced and fixed salary/qualification clauses
separated by semicolons/commas, unrelated credential claims in the same record,
indirect identity-service mentions and future/negated activities. Those fixes
postdate the first full-suite launch. That first run is therefore superseded,
not validation of the final revision. The final full suite was rerun alone against
the reviewed code: **2319 passed, 1 skipped, 13 warnings in 1466.10 seconds
(24:26)**. The optional real-embedding integration test remains opt-in. Warnings
are third-party LangSmith deprecations; pytest-asyncio also reports its unset
future fixture-loop default at startup. The three new files add **89 cases**.
Checks use the pinned Python 3.14 environment and environment/dependency
conformity checks. Previous test totals in other audit documents do not validate
this follow-up.

## Operational impact

No new dependencies, model downloads, runtime configuration or migrations. No
saved report, profile, SkillsBank or CV is edited; no batch is automatically
retried. There is no production rollout or restart as part of implementation.
Queue capacity is a separate operational change, not part of this correction.
Existing reports require fresh analysis after a separately authorized deployment.
Recovery retains the existing bounded attempt budgets and validators are not
weakened to admit failed analyses.
