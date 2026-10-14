# Safe manual CV edits

## Verified cause

The old `save_resume_edit` computed `changed` by comparing every summary, experience bullet and project description/technology list with the output of a new full `FactValidator.validate` pass. It also checked **every** submitted skill against current bank eligibility, including retained saved wording. Neither check distinguished edited fields from saved fields.

Read-only verification found three real saved documents containing `Playwright browser automation`. After removing only that skill, the newest document triggered the project-comparison branch, specifically **`project_1_description`**; summary, experience and retained-skill conditions were false. Two other saved documents triggered both project and summary comparisons. These were changes proposed by global revalidation, not submitted edits. The new scoped validation returns zero blocking issues for the same removal. No production document, profile or bank was written by this reproduction.

A second full validation in `_regenerate_artifacts` could then rewrite unchanged content after admission. Stale `selected_skill_ids`, inferred using a positional zip with displayed skills, could resurrect a removed choice. Rebuilding a typed editor copy also discarded the private saved summary attestation.

## Behavior

`FactValidator.validate_manual_edit` uses the existing source validator to check new/modified claims and audit saved claims. It returns the exact edited document plus separate field issues and source-review warnings, rather than substituting the globally regenerated document.

- Removed skills, interests, bullets and optional project information are omissions, not new claims. They stay removed.
- Retained skills do not need reapproval to permit an unrelated deletion. Unverifiable or overstated saved wording is flagged separately, without adding approved bank IDs to it.
- New skill wording must be eligible and approved at the displayed level. Unknown technology and proficiency inflation are rejected with the field, reason and correction.
- Changed summary/headline/project text must survive current source validation. Modified employment bullets must also be supported by their own employment citations, with the correct owner; auto-filled unrelated facts cannot approve them. Changed project claims require project-owned references.
- Skill IDs are resolved from approved displayed wording, never list positions. Unchanged references and private summary attestations are preserved; edited evidence references can be normalized to stable IDs.
- Legacy/source-review warnings are shown in the editor and saved in metadata for preview. The preview uses a neutral source-validation-notes label because these claims were audited, not silently removed or approved.

Normal generation/reset validation remains available. The manual export path accepts only the server's scoped validation result, prevents layout fitting from changing its content, and retains staged PDF/DOCX rendering and atomic commit/rollback. Profile and Skills Bank are not modified by document deletions.

## Verification

Full suite: **485 passed, 2 skipped**. After the final parser/citation adjustments, all **16 editor regressions** passed. Ruff and whitespace checks passed.

The regressions use authenticated, CSRF-protected edit requests, real PDF/DOCX export and reopened saved documents. They cover single/multiple/all-skill removal, unchanged summary/projects/experience, legacy/inconsistent IDs, unknown technology, inflated levels, changed-summary and employment rejection, valid source-backed modification, optional omissions, summary-attestation preservation, comma/whitespace-containing labels, project reference corruption, export failure before commit and metadata-save failure after replacing artifacts. Both rollback cases preserve prior JSON/metadata/PDF/DOCX bytes. Deletion tests verify unchanged private profile/bank bytes and that the original generated CV remains intact.
