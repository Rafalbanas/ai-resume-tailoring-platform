# Evidence-based matching

The deterministic validator assesses the supplied advertisement against saved
facts. A model can suggest phrasing but cannot establish competence, invent an
employment period, or change a source requirement's priority.

`evidence_matching.py` applies directional rules to employment facts, project
facts and technologies, language declarations, and eligible manually verified
skills. Manual attestations retain their original IDs and descriptions. Job
titles and previously generated CV wording are not evidence of activities.

Examples of directional matching:

- Operational SQL Server/T-SQL queries support working SQL knowledge. Generic
  SQL does not establish T-SQL or SQL Server specifically. DBA, cluster work,
  advanced proficiency and tuning require separate evidence.
- Documented HTTPX/JSON/REST integration supports API integration. Debugging,
  authentication, payloads, status codes and production scope are assessed
  separately; Python alone does not prove integration.
- AI coding tools support using assistants, not experience as an AI engineer.
- Ticket handling is related evidence, not proof of independent ownership from
  intake to closure. Engineering escalation does not prove Product collaboration.
- B2 does not meet B2+ or C1. Native Polish meets Polish language requirements.

Each requirement retains the original quote, interpretation, required level and
years, status, evidence, source references and explanation. `strong`, `partial`,
`missing`, and `absent` remain the stored status values for compatibility; the UI
labels them Confirmed, Partial, Not confirmed, and Confirmed gap. Missing evidence
does not establish a lack of competence. Explicit negative facts can establish a
gap. Ambiguous combined conditions are flagged for source review.

## Advertisement interpretation and scoring

`job_sections.py` separates capabilities from explicit preferences, including
parenthetical preferred programming languages and accepted alternatives. OR
needs one qualified branch. AND needs every condition; shared qualifiers apply
to each branch. Original wording is preserved for individual review.

No Fluff Jobs technology tags are emitted as `PORTAL TECHNOLOGY TAGS`, with
unspecified employer priority and their language levels retained. Legacy short
`MUST HAVE` tag blocks alongside a separate `REQUIREMENTS` section are interpreted
the same way. They remain visible as role competencies rather than becoming
extra mandatory prerequisites. A standalone employer `Must have` section keeps
its mandatory meaning.

Equivalent SQL clauses share scoring weight while retaining individual rows and
source quotes. Different scopes (e.g. SQL vs database tuning, integration vs API
debugging) do not share weight. Explicit AND groups use their weakest condition.
Mandatory confirmed/partial/unconfirmed evidence weights remain 1/0.5/0;
preferred clauses and portal tags do not create mandatory blockers. The HIGH
threshold additionally requires every mandatory condition to be confirmed. The
assessment is evidence coverage, not hiring probability or an ATS prediction.

Relevant dated employment periods are merged before calculating tenure.
Overlapping periods count once. Ongoing periods end on the evaluation date;
month-level historical end dates include that month. Year-only dates, titles
without activity facts and undated projects cannot establish precise tenure.

## Profile updates and compatibility

All new report fields have defaults, so saved profiles, job descriptions and
reports remain loadable. The master-profile and skills-bank schemas are unchanged.
The stricter Truth Lock used by CV generation and export is unchanged.

Apply an explicit, private additive plan using:

```sh
python -m app.cli enrich-profile --data-dir data --plan /private/enrichment-plan.json --dry-run
python -m app.cli enrich-profile --data-dir data --plan /private/enrichment-plan.json
```

Supported plan keys: `summary_facts`, `skills` (category to list),
`experience_facts` (existing company owner and facts), `project_facts` (existing
project owner, facts and technologies), and `bank_skills` (new verified skills or
explicit updates by ID). Existing arrays and evidence are extended without
duplicates. Verify each assertion before adding it. An unverified skill must keep
`verified=false` and `allowed_in_cv=false`.

The command validates both files and every source reference before writing,
retains backups under `data/.drafts/profile-backup-*`, restores both files if a
write fails, preserves permissions/ownership and is idempotent. Adding facts does
not change existing stable fact IDs. After offline profile changes, restart the
application to refresh its in-memory profile and bank. A Git rollback alone does
not restore ignored private data; restore the corresponding profile backup too.

Regression coverage includes contextual matching, AND/OR, preferences, B2/B2+,
negative versus missing evidence, source provenance, duplicate weights, employment
intervals, additive updates/rollback and the public OneRail fixture with synthetic
candidate evidence. Private control runs and PDF/DOCX artifacts are not committed.
