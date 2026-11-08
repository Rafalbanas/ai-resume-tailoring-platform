# Demo media

Captured locally on 2026-11-08 from an independent, temporary data directory, not the owner's account or deployed service.

- Candidate: **Alex Example**, fictional; email `alex@example.com`; no phone number.
- Company/offer: **Fictional Lantern Labs / Technical Support Specialist**, synthetic.
- Provider: **Ollama**, model **`gemma4:12b-it-q4_K_M`**, automatic fallback disabled; no mock provider or cloud fallback.
- Login was completed before recording began. Credentials, cookies, CSRF tokens, logs and generated document files are not included here.

## Recordings

The [local gallery](../demo.html) provides native video players and clickable screenshots.
GitHub shows HTML source rather than hosting the page; see the main README for local viewing.

- [Generation](cvtailor-gemma-generation.webm): approximately 130 seconds, actual browser capture with AI waiting time retained. Ends around the start of the export attempt. Reduced to 5 fps and 1152 × 800 for repository size; playback is not accelerated.
- [Report walkthrough](cvtailor-gemma-report.webm): approximately 39 seconds, a separate visit to the saved report, source/summary review, failed export status and History. No new AI generation is performed in this walkthrough. Same size/frame-rate reduction, no acceleration.

Both are silent WebM/VP9 files. These are two separate captures, not a continuous end-to-end success recording.

## Animated README preview

`cvtailor-report-preview.gif` is a four-screenshot slideshow (2.5 seconds per slide),
not an excerpt with real playback timing. It shows the form, match report, export
timeout and History, with a visible synthetic-demo label. Rebuild from the existing
PNG captures using `.venv/bin/python scripts/build_demo_preview.py` (Pillow required).

## Results and limitations

Analysis and the CV draft completed. The in-app export failed with **Document processing exceeded the time limit**; the error remains visible in the status screenshot and report video. A separate isolated direct PDF-rendering check completed in approximately 42 seconds, but that does not validate the full application PDF/DOCX export. No successful in-app PDF/DOCX download is claimed.

The PNG files show the submitted form, full report, initial export failure and History. `match-report-overview.png` is a crop of the full report for the main README, not a different result. The capture scripts, account credentials, raw outtakes and diagnostics remain outside the repository.
