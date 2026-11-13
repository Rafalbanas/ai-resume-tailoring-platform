# Community Launch

## Proposed Repository Description
Self-hosted AI resume tailoring without invented experience. Match documented facts to job requirements, review Truth Lock checks, and export PDF, DOCX or HTML. FastAPI, Ollama/Gemini, Docker and Kubernetes/K3s. Apache-2.0.

## Repository Topics
resume-builder, resume-generator, ai-resume-builder, ats-resume, job-application, fastapi, ollama, self-hosted, rag, python, kubernetes, k3s, docker, gemini, llm

GitHub allows at most 20 topics, each at most 50 characters. These 15 use supported
lowercase/hyphen syntax. `ats-resume` describes the output/use case, not certified
compatibility with every recruitment system. No star-count or adoption badge is proposed.

## Ownership Instructions (Owner Only)
To update the repository identity, use the GitHub CLI or the web UI:
- **Web UI**: Navigate to the **About** section on the repository home page to edit the Description and Topics. Change the Social Preview in **Settings > General > Social preview**.
- **GitHub CLI**:
  The following are **owner instructions, not commands executed by this change**.
  `--add-topic` retains existing topics; remove broad/redundant ones with the About
  gear first so the total remains at most 20.

  ```bash
  gh repo edit Rafalbanas/ai-resume-tailoring-platform --description 'Self-hosted AI resume tailoring without invented experience. Match documented facts to job requirements, review Truth Lock checks, and export PDF, DOCX or HTML. FastAPI, Ollama/Gemini, Docker and Kubernetes/K3s. Apache-2.0.'
  gh repo edit Rafalbanas/ai-resume-tailoring-platform --add-topic resume-builder,resume-generator,ai-resume-builder,ats-resume,job-application,fastapi,ollama,self-hosted,rag,python,kubernetes,k3s,docker,gemini,llm
  ```

  Existing topics observed during this audit: `ai`, `automation`, `docker`,
  `github-action`, `job-search`, `llm`, `python`. No settings were changed.
  Verify private vulnerability reporting is enabled before relying on its link;
  [SECURITY.md](../SECURITY.md) already points to it. No license change is needed.

## Social Preview Specification
- **Size**: 1280x640
- **Source**: Synthetic existing screenshots (do not use production data).
- **Composition**: CVTailor name, “AI resumes without invented experience”, one
  legible crop of the fictional match report, and “Ollama · Gemini · K3s”. Keep
  essential text away from edges for cropped previews. Use the real screenshot,
  not a decorative UI mockup. An upload-ready image is not included in this change.

## Versioning and Release Proposal
### SemVer Before 1.0
Versions starting with `0.x.x` indicate active development; document API/schema
changes explicitly even before 1.0. Use `v0.MINOR.PATCH` for releases and
`v0.MINOR.PATCH-rc.N` for candidates. Reserve 1.0 for a documented compatibility
policy; SemVer then reserves breaking public-API changes for a new major version.
Tags do not currently configure the application version. Keep existing commit/digest
image provenance; do not change the deployment workflow for a marketing release.

### Prerelease Proposal: v0.1.0-rc.1
Release `v0.1.0-rc.1` is proposed. Version `v0.1.0` will only be released after full verification.
No published releases were returned by `gh release list` during this audit.
Recheck before choosing a tag. Prepare notes describing supported platforms,
provider/privacy boundaries, known export issues, migration needs and validation
revision; exclude generated candidate documents. Publication needs explicit owner approval.

## Release Checklist
- [ ] Run `python scripts/sync_readme.py --check`
- [ ] Run `ruff check .`
- [ ] Run `pytest -q`
- [ ] Verify CI Full and Split images
- [ ] Verify mock behavior (never claim LLM results)
- [ ] Verify Ollama and, only with consent and a private API key, Gemini using
  fictional inputs; record the model/revision and actual failures. Never invent credentials.
- [ ] Review/confirm the summary, download **and open** PDF/DOCX, inspect text,
  links and layout, and test offline HTML/ZIP separately.
- [ ] Verify links, screenshot provenance, fictional data, keyboard use, focus and
  mobile/zoom behavior. Document accessibility limitations, not compliance claims.
- [ ] Ensure K3s documentation is preserved/read-only
- [ ] Confirm owner approval before merging to `main` (push/merge to `main` triggers CD)
- [ ] Confirm infrastructure configuration is unchanged; review the existing
  [rollback/backup procedure](kubernetes-production.md) without running it.
- [ ] Obtain separate owner approval for publishing the release. Do not deploy,
  retag production images, or change runtime configuration as part of publication.

## Roadmap
- (P0) Reproducible clean Linux Docker mock E2E export recording opening PDF/DOCX
- (P1) macOS/Windows host-network onboarding matrix
- (P1) PL/EN retrieval evaluation (real local embeddings clearly optional)
- (P2) Targeted accessibility audit (UI/export)

## Suggested Beginner Issues (Non-Created)
*Note: The following are proposed issues for community contribution and have not been created in the tracker.*

1. **Troubleshoot permissions/ports with reproducible examples**
   - *Acceptance criteria*: extend the [Quick Start](quickstart.md) with one
     reproduced rootless-Docker permission case and one occupied-port case;
     state the platform and safe fix. No `chmod 777`, public binds, stopping other
     services, or Compose changes.
2. **Add a plain-English glossary for candidate evidence**
   - *Acceptance criteria*: explain Truth Lock, BM25, candidate attestation and
     learning vs. eligible skills in the docs index, link to the existing source
     guides, and avoid semantic-search or external-verification claims.
3. **Document a keyboard-only walkthrough**
   - *Acceptance criteria*: extend [ACCESSIBILITY.md](../ACCESSIBILITY.md) with
     login → analysis → summary review → download steps, browser/zoom details,
     observed focus barriers and fictional screenshots. No unsupported WCAG claim.

## Glossary
- **Truth Lock**: Independent source checks, not proof every claim is true. See
  [validation and manual editing](safe-manual-cv-edits.md).
- **BM25**: Default lexical retrieval; see [RAG design](rag.md).
- **Attested skills**: Candidate-maintained skills linked to profile evidence or
  explicit manual verification, not an independent credential check.

## Community Outreach
### LinkedIn Post Draft
I built CVTailor around a constraint: tailor the presentation, not the experience.
It compares a job offer with a candidate-maintained profile, shows supporting
evidence and gaps, then checks the CV draft with Python-side Truth Lock rules.
Ollama works locally; Gemini is an explicit cloud option. The project also includes
K3s deployment and isolated document processing.

It is Apache-2.0, owner-managed and still needs human review—not a promise of zero
hallucinations. The repo has fictional screenshots and a local mock walkthrough.
I'd welcome feedback on onboarding and clarity:
https://github.com/Rafalbanas/ai-resume-tailoring-platform

### Technical Community Post Draft
CVTailor is an Apache-2.0 FastAPI/Jinja2 resume-tailoring app. Direct Ollama/Gemini
generation retrieves candidate facts with request-local BM25; independent Python
validation constrains source IDs, skill eligibility and scope. Hybrid embeddings
and a bounded LangGraph path are optional and default-off, not required architecture.
The repository includes Docker role images, K3s/RBAC/backup operations and CI
security/layout checks. It is built for private self-hosting, not public multi-tenancy.

The current Ollama video shows analysis and drafting, but export timed out—there
is no successful E2E recording claim. I'd especially appreciate clean-install,
document-export and accessibility feedback using fictional data. Source and setup:
https://github.com/Rafalbanas/ai-resume-tailoring-platform

Both posts above are unpublished drafts. Do not post them automatically.

## Related Documentation
- [Project README](../README.md)
- [Contributing Guide](../CONTRIBUTING.md)
- [Security Policy](../SECURITY.md)
- [Deployment and Continuous Delivery](deployment.md)
