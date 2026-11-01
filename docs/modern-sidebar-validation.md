# Modern Sidebar: diagnosis and safe delivery

## Scope and diagnosis (2026-10-30)

Work started from clean `feat/custom-cv-ai-editor` at `d10094c`, on working branch
`fix/modern-sidebar-editor`. No production data, services or manifests were changed.
The private `/root/cvtailor-reference/` files remain outside Git.

Reference PDF: one A4 page. Reference HTML: navy `#112e4b`, 62 mm sidebar,
148 mm main column, 12 mm top spacing, roughly 8–9 pt body text. The supplied bad
export has two pages and places sidebar text in a single normal text flow.
The text exporter previously implemented “Modern” as a heading color only, while
opening a structured CV in the editor forced ATS and forgot the original selection.
Flattening all inline HTML nodes with newlines also damaged logical entry boundaries.

The correction restores real columns in text PDF/DOCX, persists template selection
and makes preview use the exact accepted PDF exporter. It does not modify the
existing structured-resume PDF/DOCX pipeline or claim pixel-identical reconstruction
of an imported PDF, arbitrary Word layout, or a lost photograph.

## Reproducible local checks

```sh
.venv/bin/ruff check app tests
.venv/bin/pytest -q tests/test_custom_cv.py tests/test_custom_cv_storage.py \
  tests/test_text_cv_export.py tests/test_custom_cv_ui.py tests/test_modern_sidebar.py
.venv/bin/pytest -q
.venv/bin/python -m pip check
.venv/bin/python scripts/check_environment.py --dev
git diff --check
```

Poppler and LibreOffice are optional external test dependencies, not new application
dependencies. The visual baseline contains fictional data only. Expected geometry:
62/148 mm, one page for the synthetic reference-shaped content in PDF and DOCX
(LibreOffice conversion); oversized sidebar/main content retains all numbered lines
across pages. Test fixtures isolate application storage and mock provider calls.

Private inspection outputs may be retained in
`/tmp/opencode/modern-sidebar-validation/`; do not commit or publish those files.
Text reconstructed from the supplied reference HTML fits one PDF page and one
DOCX-to-PDF page without deleting content. The original photo is not part of a text
import, and Word/LibreOffice can differ in line metrics.

The local virtualenv was not changed. The environment checker currently reports
pre-existing pin drift: FastAPI 0.143.0 vs 0.161.1, pydantic-settings 2.15.0 vs
2.16.1, Playwright 1.63.0 vs 1.64.1, pypdf 6.20.1 vs 6.21.2, Pillow 12.3.0 vs
13.0.0 and Ruff 0.17.0 vs 0.17.2. `pip check` succeeds, but that does not establish
exact-pin compliance. Validate the immutable release image against repository pins
before delivery; do not “fix” the production environment in place.

### Recorded results

- Final focused suite on the completed change: **76 passed**, including PDF raster
  comparison, browser desktop/mobile UI, one-page DOCX conversion and persistence.
- The saved full-suite log reports **1263 passed, 4 failed** in 1398 seconds.
  This run started before the last small contact-section/heading refinements;
  those refinements are covered by the final focused suite. The asynchronous shell
  completion notification was subsequently cancelled by an OpenCode server restart;
  the complete pytest summary remains in `full-suite.txt`.
- The four failures were browser timeouts: three parameterizations in
  `test_browser_extractor_security.py` and the shared-login browser test. Rechecking
  those four separately produced **2 passed, 2 failed**: shared login and blank-popup
  passed; main-page and popup still exceeded the extractor's deadline.
- A detached clean worktree at original `d10094c`, using the same virtualenv,
  reproduced **all three extractor timeouts**. That establishes an existing
  baseline/environment issue rather than a new editor regression. Browser security
  timeouts/policies were not changed to make the suite green. A completely green
  full-suite run on the exact-pin release environment remains a delivery check.
- Ruff (`app tests`), `git diff --check` and `pip check` passed. Exact environment
  pin validation failed as documented above, not silently skipped.
- Private reference-shaped text exports were manually inspected: **one PDF page,
  one LibreOffice-converted DOCX page**. A 180-skill/200-incident stress sample
  produced four DOCX-to-PDF pages with zero missing numbered lines; the automated
  PDF overflow test likewise retains all content.

## Deployment is NOT performed by this change

Read-only inspection found the active service in K3s namespace `cvtailor-prod`:
`cvtailor`, `cvtailor-processing-owner`, `cvtailor-processing-demo`, using image
digest `sha256:d2d2820898e4afc24cf75d25084f30c144afd7cecd3854bb72917372c0049fbf`.
The standalone `cvtailor-demo` deployment was scaled to zero. The API container
starts `python /opt/cvtailor/runtime.py`; host Nginx reaches loopback port 18000.
`GET http://127.0.0.1:18000/health` returned `{"status":"ok"}`. Local Compose is
not the active production launch mechanism. Recheck this inventory before delivery.

After separate approval:

1. Review/commit the branch and create an immutable build from that exact revision.
   Do not build from or overwrite private account directories. No dependency or
   database migration is needed. Do not use a blanket Docker/K3s cleanup.
2. Validate the image in a separate staging instance with synthetic data, mock AI,
   independent credentials and no production PVC mounts. Smoke-test import, modern
   selection, AI proposal/accept, reopen, duplicate, preview, PDF/DOCX and ATS.
3. Take the existing application-consistent backup, record active manifests/image
   digests and account-volume paths, and verify that no generation/export is active.
   Use the existing deployment admission/coordination procedure. Never replace or
   reinitialize production data with test fixtures.
4. In the approved maintenance window update API and document workers to matching
   revisions using the existing K3s release procedure (not `docker compose up`).
   Both ends need the exporter fix; stale worker images keep the old visual bug.
   Preserve environment, secrets, PVCs and the current single-replica strategy.
5. Check readiness/health, authenticated preview and both exports with a synthetic
   CV. Verify template persistence and page count. Check owner/demo isolation.
6. On failure restore the recorded image digests/manifests, not account data.
   The additive `template_name` field can remain; no destructive rollback migration
   is required. Keep the backup until the release has been accepted.

The original implementation request did not authorize deployment. The user
subsequently authorized deploying this change after readiness checks. Delivery
uses a locally built/imported immutable image and the installed drain/rollback
wrapper; it does not require `git push` or external image publishing. Before the
release, production source hashes for `app/`, `templates/`, `static/`, Dockerfile
and requirements were compared with original `d10094c`: all matched. The running
image's revision label is not present as a local Git object, so source comparison
is recorded rather than asserting Git ancestry. Production's existing runtime
passes its exact dependency-pin checker; the documented drift is in the host
virtualenv, not in the deployed container.
