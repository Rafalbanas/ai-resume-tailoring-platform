# Modern Sidebar: Safari verification and deployment follow-up

## Starting state and reproduction

The worktree was clean at `e671bea2afffb1d9d655a74209bf692b8091b214`.
The actual CVTailor container, listening on loopback port 18000 behind
`cv.banas.dev`, reported build `d49f40cffe614b9a8a20113768b667d3f0f25655`
(timestamp 2026-10-11T10:53:49Z). Its renderer/CSS hashes differed from HEAD.
Port 8000 belongs to a different application and was excluded from verification.

The latest saved record, selected by metadata modification time, was
`2026-10-11_capgemini_infrastructure-engineer-intune`. Existing resume,
metadata and profile/photo data were used without running any model.
Authenticated production preview screenshots and DOM measurements were captured
before deployment in Chromium and Playwright WebKit 26.0, at 390 × 844 pixels.
WebKit reproduced the white paper ending halfway through experience, continued
sidebar/text on grey background, fragmented contact URLs and consent above paper.

## Actual causes

* `static/app.css` had `.paper-frame .resume-document.modern-sidebar` with
  `height:297mm`, overriding normal document height. Main content exceeded it;
  transparent main-column background exposed the frame underneath. Fixed
  mobile `zoom:.42` and browser text sizing made the mismatch worse in WebKit.
* The running consent footer is a sibling before the article. Screen browsers
  ignore WeasyPrint's `position:running(consent)` and margin-box instructions,
  so it appeared in normal flow above the article. Browser flow did not have
  the PDF engine's page boundaries/backgrounds.
* Full contact URLs combined with `overflow-wrap:anywhere` in the narrow sidebar
  produced several tiny link fragments.
* The saved model draft had one WAVE partner-support sentence. Truth Lock's
  deterministic summary builder selected both an identity source and a detailed
  experience source for the same support fact, introducing the repetition.

The preceding `e671bea` already introduced real PDF-backed pages, page backgrounds,
reserved consent margins and verified-clause deduplication, but was not deployed.
This follow-up removes obsolete fixed-height/zoom screen rules, adds Fit width /
Enlarge controls and uses Email, LinkedIn, Website and GitHub sidebar labels with
unchanged full hyperlink targets. ATS/DOCX keep their existing contact presentation.
The portrait's interactive hit target no longer repaints its image/initials at a
browser-dependent scale; its image remains in the rasterized PDF page. Preview
header actions also wrap without splitting words at desktop widths.

Document proportions, export typography and saved content are unaffected by zoom.
The preview contains separate actual A4 pages. Page images use the export renderer,
with clickable PDF link overlays and accessible text. No content is hidden to fit.
Deduplication runs on in-memory copies and retains identity, technical-support
qualification, issue-resolution detail and source IDs. Fact validation/Truth Lock
are retained; neither the private master profile nor skills bank was edited.

## Export and visual checks

Controls are separate private artifacts in `audit/sidebar-20261011/private/`
(ignored by Git and excluded from the Docker build). No history record or earlier
export is overwritten. Saved latest, shortest nonempty and longest records were
used. A pagination stress case repeats existing experience/skills only in memory;
it is a layout fixture, not a new candidate record.

| Case | Modern PDF pages | ATS PDF pages | DOCX pages, either theme |
| --- | ---: | ---: | ---: |
| Latest Capgemini | 1 | 2 | 2 |
| Short saved ALOIS | 1 | 2 | 2 |
| Long saved Motorola | 1 | 2 | 2 |
| Pagination stress case | 3 | 4 | 4 |

Every page of all eight PDFs was rasterized and visually inspected. All eight
DOCX files were converted with LibreOffice and every page inspected; corresponding
pages are pixel-identical between theme choices. Full experience bullets and
project descriptions were checked against extracted PDF text. Renderer box checks
verify paper bounds and the reserved footer area on every page. Inspected pages
have full backgrounds, no out-of-paper content, clipping, footer overlap, blank
pages or consent-only pages. Historical sparse/empty records were also rendered
as one-page controls during initial checks.

Browser checks cover both themes and all four cases on phone and desktop, in
Chromium and WebKit. They inspect every page, unchanged A4 aspect ratio, fit width,
Enlarge/reset behavior and horizontal scroll confined to the preview. Contact
links, theme selection and opening photo controls were checked. WebKit is available;
this is Linux Playwright WebKit, not a physical iPhone or Apple's Safari binary.

## Regression and preservation checks

* Full suite: 239 passed, 6 failed. All six reproduce on an isolated unchanged
  archive of `e671bea`: affected baseline modules have 21 passed and the same
  6 failures. They are the three existing qualification-assessment expectations
  in `test_audit_safety.py` and three existing interests/legacy one-page-fit
  expectations in `test_interests_and_thesis.py`.
* Targeted pagination, theme persistence, photo and fact-validation suite: 17
  passed, including
  a new regression verifying full contact targets, a single annotation per short
  label and immutable profile data.
* Ruff and `git diff --check` pass. Browser checks report no JavaScript exceptions.
* SHA-256 manifest covers 203 original files: environment configuration,
  profile, skills and every original history artifact. All are unchanged.
* Compared with control exports produced by the still-running older container,
  DOCX ZIP members are identical except the intended summary merge and core
  timestamp. ATS PDF extracted text is identical after that same summary merge.
* No Ollama/Gemini calls, profile edits, skill-bank edits or history rewrites.
  No new regression requiring a revert was found.

## Deployment procedure

The starting deployment was older than the repository. After verification, the
follow-up commit is deployed by rebuilding only the `cv-tailor` Compose service
with its exact `APP_BUILD_SHA` and timestamp, then recreating that service while
retaining the existing environment and data volume. There are no queued/running
AI tasks. The previous image is tagged locally for recovery.

Post-deployment verification must check the authenticated live preview at
`https://cv.banas.dev`, static asset build version, container source hashes,
phone/desktop screenshots and the original data manifest. Its actual outcome and
runtime SHA are recorded separately in the final task report/private audit output;
this file documents the checks before deployment and does not itself assert a
successful release. Original downloaded historical exports remain preserved;
new control exports live separately in the audit directory.
