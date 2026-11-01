# Stage One Release Validation

## Final release run

`/tmp/opencode/cv-repair/full-release.xml` and `.log`: **1327 passed, 0 failed**
in 1336.23 seconds. One Starlette/httpx deprecation warning remains; it is not
a failed test. This run includes all new source, portal-level and queued-export
regressions. Ruff and diff whitespace checks passed before this run.

## Earlier failed run (preserved for transparency)

Earlier full pytest results are recorded in `/tmp/opencode/cv-repair/full-final.xml` and `.log`.
- **Passed:** 1319
- **Failed:** 2

### Failures
- `tests/test_academic_ml.py::test_basic_academic_wording_survives_generation_and_exports[modern_sidebar]` (metrics worker timeout 60s)
- `tests/test_browser_extractor_security.py::test_all_browser_pages_block_requests_to_private_services[main-page]` (Chromium launch deadline)

### Isolated follow-up
- Both failure paths plus all browser security cases were rerun without a parallel test process: **6 passed in 53.19s** (`/tmp/opencode/cv-repair/timeouts-isolated.xml`). No assertions or security controls were disabled for this rerun.
- The next serial full-suite run passed **1321 tests** (`/tmp/opencode/cv-repair/full-serial.xml`). Subsequent regressions for inline source coverage, repeated portal levels and queued browser export are included in the final **1327-test** release run above.

## Environment & Benchmarks
- **Ruff / check_environment --dev / pip check:** Passed
- **Benchmark (`tests/test_benchmark_api.py`):** 6 passed
- **New safety/export regressions:** 56 passed across background exports, generation queue, benchmark API, source qualification guards and shared-account isolation; 2 additional repeated-portal-level tests passed separately. All are also included in the final full-suite run.
- **Runtime image:** `cvtailor:queue-benchmark-20261101` built successfully; pinned-environment verification and isolated imports/export-task/OpenAPI/source-segmentation smoke checks passed. This does not substitute for the full test suite.
- **Benchmark real URL run (`5648e4b739144bb7b8157afe52a38e93`):** 3 extraction_failed, 0 model calls. Result does not constitute a valid measurement.

## Status & Blockers
- **Measured experiments:** See [the sanitized findings](benchmark-results-stage-one.md). Live-import and verified-snapshot modes are distinguished. No validated full/cleaned pair supports a safe optimization claim. Original account tasks were never interrupted for measurement.
- **Publication / Deployment:** Test gate passed. Dependent PRs must remain unmerged; deployment must drain active requests/tasks and retain rollback images.

## Note
Passing software tests does not turn failed model experiments into successful
optimization results. Cleaning remains benchmark-only; full integration-token
and n8n API coverage belongs to the separately approved second phase.
