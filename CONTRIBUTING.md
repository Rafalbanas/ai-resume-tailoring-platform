# Contributing to CVTailor

Small fixes, reproducible bug reports, documentation improvements, and
accessibility feedback are welcome. This is a personal, single-owner project;
review and support happen as the maintainer has time. Discuss substantial
changes in an issue before implementing them.

Follow the [code of conduct](CODE_OF_CONDUCT.md). Report vulnerabilities using
the private channel in [SECURITY.md](SECURITY.md).

## Local development

Use Python **3.14**, matching Docker, CI, and the CD test job. On Linux:

```bash
python3.14 -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt
python -m playwright install --with-deps chromium
cp .env.example .env
cp data/master_profile.example.json data/master_profile.json
cp data/skills.example.json data/skills.json
```

Edit the local `.env` before starting. Set `AI_PROVIDER=mock`,
`LLM_PROVIDER=mock`, `LLM_FALLBACK_PROVIDER=none`, `PROFILE_MODE=sample`, and
`BASE_URL=http://127.0.0.1:8000`. Choose your own local `APP_USERNAME`,
`APP_PASSWORD`, and random `CSRF_SECRET`. Mock mode does not require AI API keys.

```bash
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Use the bundled example profile or fictional data. Do not copy a production
data directory or credentials into your development environment. See the
[README](README.md) for configuration and Docker setup.

## Checks

```bash
ruff check .
pytest -q
```

Run focused tests while working and the full suite before submitting code
changes. Chromium and its system dependencies are needed for browser/layout
tests. CI also builds the Dockerfile and checks application imports, PDF/DOCX
exports, and Chromium inside the image. Documentation-only changes can be
checked with link, YAML, and diff validation; describe those checks in the PR.

## Pull requests

- Branch from the current `main` and keep the change focused.
- Describe the problem, resulting behavior, and validation in the PR template.
- Add regression coverage when behavior changes warrant it. For UI changes,
  include screenshots with fictional data and check keyboard navigation,
  visible focus, zoom, and labels; see [ACCESSIBILITY.md](ACCESSIBILITY.md).
- Preserve Truth Lock and the distinction between verified skills, basic
  knowledge, and learning. Never invent candidate facts to make an example pass.
- Use synthetic fixtures and mocked external services in automated tests.
  Real AI-provider checks require your own credentials and fictional input.
- Do not commit private profiles, generated CVs, credentials, logs, or backups.
- Coordinate Python/runtime upgrades across Docker, CI, and CD. Explain
  dependency, persistence, migration, and deployment changes explicitly.

AI-assisted contributions are welcome. The contributor is responsible for
reviewing the patch, understanding its behavior, and verifying its claims and
tests before submission. A pull request does not authorize production deployment.
