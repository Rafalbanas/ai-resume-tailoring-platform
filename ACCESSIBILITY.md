# Accessibility

CVTailor aims to make job analysis, profile editing, and document review usable
with a keyboard, clear labels, readable contrast, and text that remains usable
when enlarged. Accessibility feedback and focused improvements are welcome.

## Current testing and limitations

Automated CI runs on Linux with Chromium through Playwright and exercises
document layouts and exports. These checks are not a comprehensive accessibility
audit. The project has not established WCAG conformance or certified support for
particular screen readers.

- The rendered CV preview displays page images with page labels and link
  overlays. Its document text is not exposed as a complete semantic HTML
  document for screen readers. Use the editable DOCX export as an alternative
  and check it in your preferred editor or assistive technology.
- Generated PDFs are not guaranteed to be tagged PDFs or PDF/UA compliant.
  DOCX accessibility and reading order also require manual review.
- Photo cropping, dialogs, focus handling, and two-column layouts need further
  keyboard and assistive-technology testing.
- Safari, Firefox, mobile assistive technologies, and screen-reader combinations
  do not have equivalent automated coverage to Chromium.

These are known coverage gaps, not a claim that every untested environment
fails. Report the environment and task affected so improvements can be reproduced.

## Report a barrier

Use the [accessibility issue form](https://github.com/Rafalbanas/ai-resume-tailoring-platform/issues/new?template=accessibility.yml).
Describe the task, steps, expected behavior, and browser/device or assistive
technology involved, if you are comfortable sharing that information. A diagnosis
or medical history is not needed. Use fictional profile data and redact any
screenshots or logs. For security or private-data exposure, use [SECURITY.md](SECURITY.md).

## Contributing improvements

For UI changes, check keyboard-only operation, visible focus, form labels, error
messages, zoom, and narrow layouts. Automated accessibility tools can supplement
these checks; their results do not replace manual testing. Include what you
tested and any remaining limitations in the pull request. See [CONTRIBUTING.md](CONTRIBUTING.md).
