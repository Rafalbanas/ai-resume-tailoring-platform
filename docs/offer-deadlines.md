# Offer deadlines

Job offers can have an optional **Offer valid until** calendar date. URL extraction
reads the selected `JobPosting.validThrough` JSON-LD value, or explicit closing-date
labels/attributes inside the main offer (including NFJ's posting header).
Just Join IT's application countdown is supported when it includes an explicit
calendar date; the number of days alone is never used. **Clean pasted job offer** also reads
explicit English/Polish deadline labels. Publication dates, relative durations,
numeric timestamps and ambiguous slash dates are not converted into deadlines.
Related-offer sections are excluded; conflicting dates remain unknown, including
differences between JSON-LD and the visible application countdown. Correct these
manually after checking the publisher. Not every
portal publishes a supported deadline: missing dates stay **Not provided**.

The initial job form allows manual entry, correction or clearing. Autofill does
not overwrite a date the owner has edited or explicitly cleared, including edits
made while a request is running. Custom CVs do not have offer deadlines.

Analysis and history show the date and **Past stated deadline** when it is before
the current UTC calendar day. A deadline equal to today is not expired. An ISO
datetime supplied by a publisher retains its written calendar date, without
timezone conversion. This is informational: it neither blocks generation nor
changes the match score, and it does not verify whether the publisher still
accepts applications. The date is not added to CV document templates.

Use **Edit offer deadline** in analysis/history to update that record. Clearing
the field explicitly marks the date unknown. Only authenticated non-demo accounts
can edit, with the normal CSRF, rate-limit, account-storage and quota checks.

## Persistence and compatibility

Initial dates are optional `offer_valid_until` ISO dates in job data and generated
metadata; batch extraction propagates them to child jobs and batch results.
Older records without the field continue to load as unknown. No migration or
configuration is required.

Edits are atomically written to `.drafts/<id>.deadline.json` or
`generated/<slug>/offer-deadline.json`, using `{"offer_valid_until": "YYYY-MM-DD"}`
or an explicit JSON null. Missing sidecars retain the original date; null clears
it. The sidecar overlays the original job when loaded, without modifying the
stored job, report, PDF, DOCX or export/presentation metadata. An analysis draft
and an already exported application are separate records: edits are local to
the selected record. A new export uses its draft's current date. Application
duplication copies its sidecar; deletion/retention removes associated sidecars.

Tests use fictional data and mocked extraction/providers. Chromium regressions
cover autofill, manual clearing and in-flight edits. Screen-reader, Safari and
Firefox support have not been separately audited.
