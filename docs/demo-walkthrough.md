# Demo Walkthrough: CVTailor

This document provides a structured scenario for recording a demo of the CVTailor application.

## Scenario Overview
- **User Profile**: Alex Example (fictional)
- **Target Job**: Technical Support Specialist (fictional)
- **AI Model**: Ollama `gemma4:12b-it-q4_K_M` (No fallback)

## Recording Steps
1. **Form Submission**: Load the fictional Alex Example profile, then enter a fictional company, the target "Technical Support Specialist" role and a synthetic job description in the job form.
2. **Analysis**: Show the system analyzing the provided profile against the job requirements.
3. **Generate CV**: Trigger the CV generation process and show the progress.
4. **Review & Export**: Demonstrate the review screen where the CV can be inspected and exported to PDF/DOCX formats.
5. **History**: Show the saved application, its preview and the available PDF/DOCX downloads.

## Technical Notes
- **Latency**: AI response time depends on the server. If editing out or accelerating waiting time in the video, disclose the cut or speed-up and do not present the edited duration as measured generation latency.
- **Warnings**: Do not hide any system warnings or errors during the recording; they should be captured as they appear.
- **Capture status (2026-11-08)**: Local Gemma analysis and CV text generation completed with fallback disabled. The first in-app PDF/DOCX export timed out; a separate direct PDF-rendering check succeeded. The available videos document generation and a separate report/status walkthrough, not a successful full export. See the [README recordings](../README.md#see-it-working).

For a fresh Linux checkout without a real AI provider, follow the separate
[mock walkthrough](quickstart.md). Label mock captures explicitly. A future
end-to-end recording must include successful downloads and opening both generated
documents; do not hide the current capture's timeout or replace its provenance.

## Privacy & Security
- **Confidentiality**: Ensure that no real logins, secrets, or production data are captured in the recording.
- **Reference**: See [recording-demo.md](recording-demo.md) for additional recording guidelines.
