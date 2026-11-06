# History sorting, time and downloadable files

History defaults to newest first **within each section** (generated CVs and
analyses without exports). Controls also sort by company, role or CV name in
either direction. Filtering and changing sort order require JavaScript; the
server still orders the unfiltered sections when JavaScript is unavailable.

Filters can be combined: company/role/name search, date-time interval, batch,
entry type, generation status, match level, recommendation and PDF/DOCX
availability. **Show downloadable CVs** selects generated entries with at least
one nonempty export file. **Clear filters** restores the default view. Filtering
is local to the loaded page: it does not trigger AI calls, edits or exports.

## Time semantics

New applications record a UTC creation time. Once both exports have passed the
normal export pipeline, the first generation completion time is also recorded.
Rechecking an existing export does not replace its original generation finish
time; the latest export check has a separate timestamp.

History displays the precise recorded completion time when available. Sorting
and date-time filters prefer that time, then recorded creation time. Older
records are not migrated or rewritten: their saved draft time, or the original
generated-JSON file modification time, is a labelled legacy fallback. A file
timestamp may be affected by copying/restoring data and is only an estimate.
If no usable time exists, the date is shown with **time unknown**. Such entries
sort last in the browser and do not match an hour-based range.

Time labels use **UTC**; date-time inputs use the browser's local timezone.
Bounds are inclusive. Reversed ranges show an accessible error and no results.

## Availability is not approval

Availability is based on actual nonempty PDF/DOCX files, not recommendation or
batch completion. A document may be downloadable while its advice is REVIEW or
SKIP; files available never means human-approved or guaranteed ATS compatibility.
An analysis or review-required draft does not gain download links until exports
exist. All normal authentication and download checks remain unchanged.

Batch membership uses saved slug, draft and child-task IDs, not shared offer URLs
or company names. Only batches linked to visible history records are listed;
rejecting an unstarted batch does not create CV records. Reads stay account-local.

Tests: `pytest -q tests/test_history_filters.py tests/test_history_filters_ui.py
tests/test_analysis_history.py tests/test_storage.py` and the canonical-export
regressions. Browser tests cover combined filters, reset, both sort directions,
local/UTC boundaries, invalid ranges, keyboard controls and narrow screens.
