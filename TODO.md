# MVP TODO

- [x] Define architecture and project skeleton
- [x] Add validated master profile as the only candidate source of truth
- [x] Implement FastAPI/Jinja2 mobile-first flow and Basic Auth
- [x] Add mock provider for local end-to-end verification
- [x] Add n8n/Gemini provider boundary and importable workflow
- [x] Validate structured LLM output with Pydantic
- [x] Enforce source-referenced facts with an independent validator
- [x] Add deterministic PDF and editable DOCX export
- [x] Add local history, secure filenames, logging, CSRF, input/rate limits
- [x] Add SSRF-safe single-URL job extraction with portal adapters and a browser fallback
- [x] Add Docker, CI, tests, and deployment documentation
- [ ] Fill `data/master_profile.json` with the candidate's real facts
- [ ] Select the existing Gemini credential after importing the n8n workflow
- [ ] Run the live n8n/Gemini smoke test with production secrets
