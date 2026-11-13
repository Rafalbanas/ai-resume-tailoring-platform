# Try CVTailor locally

This guide is for a **new, disposable Linux checkout**, using fictional data and
mock AI. It does not deploy K3s, change infrastructure, enable anonymous access,
or connect to an owner's installation. For the existing production architecture,
use the [K3s guide](kubernetes-production.md). Compose is an alternative standalone
deployment method, not a migration away from Kubernetes.

## Prerequisites

- Linux with a running Docker Engine and Docker Compose v2+ (`docker compose`).
- Git and Python 3; initialization uses only its standard library. Running the
  application directly instead requires Python 3.14 and native dependencies.
- Free loopback ports **8000**, **18002** (documents), **18004** (browser).
- Internet access for the initial Python image, packages, fonts and Chromium
  downloads. Mock AI needs no API key or Ollama model.

Check `docker info`, `docker compose version`, `python3 --version`, and `git --version`.
Docker access is a privileged capability; use an installation you control.

**Platform scope:** the existing Compose file uses Linux `network_mode: host`
to reach host-loopback Ollama, with Uvicorn bound to loopback. These commands are
not a verified macOS/Windows Docker Desktop recipe. Use a Linux VM/WSL2 environment
with its own Docker Engine, or follow [local development](../CONTRIBUTING.md) on a
compatible Linux environment. Do not replace host networking or bind the app to
`0.0.0.0` as a quick fix for this guide.

## 1. Initialize a fresh checkout

```bash
git clone https://github.com/Rafalbanas/ai-resume-tailoring-platform.git
cd ai-resume-tailoring-platform
python3 scripts/init_demo.py
```

The helper refuses existing `.env`, profile, skills, authentication, sessions,
history/task or provider-settings state. If it refuses, **use a new checkout**;
do not delete an owner's data to make initialization pass. It exclusively creates:

- `.env` from the tracked `.env.example`, with random login/CSRF/worker secrets,
  `BASE_URL=http://127.0.0.1:8000`, `PROFILE_MODE=sample`, both provider selectors
  set to `mock` and `LLM_FALLBACK_PROVIDER=none`.
- `data/master_profile.json` from the fictional **Alex Example** sample.
- `data/skills.json` with one fictional, employment-linked Python skill. A small
  bank is intentional: missing skills must not be invented to fill the CV.
- `data/ai_settings.json` with `automatic_fallback=false`. This persisted UI
  setting is important: the environment fallback selector alone is not proof
  that Ollama/Gemini fallback is disabled.

The generated files have mode `0600` and are ignored by Git. The helper prints no
passwords. Read `APP_USERNAME` / `APP_PASSWORD` in `.env` using your local editor,
not in a screen recording. Do not commit or paste that file into an issue.

## 2. Build and start

```bash
docker compose config --quiet
docker compose up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/health
```

Open **http://127.0.0.1:8000** and log in using the generated credentials.
Use this exact origin; `localhost` and `127.0.0.1` are different browser origins.
If health fails while the image builds or workers start, inspect `docker compose
ps` and retry after startup rather than assuming a successful launch.

The existing Compose stack starts API, document and browser services. Only the
API mounts `data/`; workers have independent tokens, no account mounts, bounded
resources and read-only filesystems. Authentication, CSRF, SSRF checks and native
processing isolation are unchanged. No demo account/profile is enabled.

Initial downloads and rendering startup vary by machine and network. **An
under-five-minute first launch has not been established.** Do not compare mock
response times with real LLM inference performance.

## 3. Walk through the application

Use **New match**, choose **Mock** if selecting a provider explicitly, and enter:

```text
Company: Fictional Lantern Labs
Role: Application Support Engineer

Requirements
- Python scripting for support automation.
- Operational documentation for containerized services.
Preferred
- Kubernetes administration experience.
Responsibilities
- Investigate support tickets and document repeatable procedures.
```

1. Review the match report. Kubernetes in the posting is not candidate evidence.
   Mock mode is deterministic and does not reproduce LLM interpretation quality.
2. Generate a draft with full Truth Lock. Inspect the summary, source references,
   skill level and warnings; the example's employment is fictional.
3. Choose **ATS Classic** initially. Review/confirm the summary if requested, then
   generate documents. A report or draft alone is not a successful export.
4. In History, download **PDF and DOCX**, open them in a local viewer/editor, and
   check text, links and layout. On a saved CV, also try HTML or HTML + CSS ZIP.

This is a reproducible manual acceptance scenario, **not a claim that these UI
steps have already passed on your platform**. The older
[Ollama recording](media/README.md) ends with an export timeout. The separate
[theme comparison script](../scripts/compare_resume_themes.py) checks rendering,
not the entire authenticated application flow.

For a deterministic unsupported-claim regression in a contributor environment:

```bash
pytest -q tests/test_fact_validator.py
```

The [README Truth Lock example](../README.md#what-truth-lock-does-and-does-not-do)
describes the fixture and result. It does not run a real model.

## Switch to real AI, deliberately

Do this only in a disposable instance and keep the fictional input while testing.
Mock remains the fastest way to explore without a model download.

### Local Ollama

1. Install Ollama separately on the Linux host. Check available models with
   `curl --fail http://127.0.0.1:11434/api/tags`. Select an already installed model,
   or deliberately download one with `ollama pull MODEL_TAG` after checking its
   hardware requirements. CVTailor does not install generation models for you.
2. Edit local `.env`:

   ```dotenv
   AI_PROVIDER=ollama
   LLM_PROVIDER=ollama
   LLM_FALLBACK_PROVIDER=none
   OLLAMA_BASE_URL=http://127.0.0.1:11434
   OLLAMA_MODEL=YOUR_INSTALLED_MODEL_TAG
   ```

   Replace the model placeholder. Current `.env.example` uses
   `gemma4:12b-it-q4_K_M`; it is not an endorsement for every machine.
3. Recreate the local API service: `docker compose up -d cv-tailor`.
   In the authenticated UI, keep **automatic fallback off** (the initializer's
   `ai_settings.json` already sets it off). Explicitly select Ollama for the offer.
4. Check model diagnostics and analyze the fictional offer. A reachable endpoint
   is not proof that the selected model can reliably produce the required JSON.

Local AI processing requires a trusted local endpoint and no external fallback.
Public offer fetching still contacts external websites. Optional semantic
retrieval is separate, default-off; see [hybrid setup](hybrid-semantic-matching.md).

### Gemini

Set **both** `AI_PROVIDER=gemini` and `LLM_PROVIDER=gemini`, supply your own
`GEMINI_API_KEY` privately, and recreate the API service. Keep automatic fallback
off unless you deliberately want it. Gemini sends job text and relevant candidate
analysis data to Google. Review provider terms and do not use private CV data
without understanding that boundary. No cloud-call or model-quality validation
is implied by this Quick Start.

## Troubleshooting

| Symptom | Check / safe action |
|---|---|
| `docker: command not found`, missing Compose or daemon unavailable | Install/start Docker Engine and the Compose plugin; verify `docker info` and `docker compose version` before initialization. |
| Required worker token missing | Initialize a fresh checkout, or configure independent random `PROCESSING_TOKEN` and `BROWSER_PROCESSING_TOKEN` (at least 32 characters) in your own local config. Never reuse CSRF/login secrets. |
| Port occupied or container name `cv-tailor` already in use | Do not stop an existing installation. Use a separate disposable Linux host/VM. The shared Compose configuration fixes service ports and a container name. |
| Permission denied writing `data/` | The existing entrypoint adjusts the bind-mounted data directory for UID 10001. Inspect local ownership and Docker/rootless permissions; do not use `chmod -R 777` or run workers as root. |
| Login loops, CSRF/origin rejection | Use `http://127.0.0.1:8000` consistently with `BASE_URL`; clear only this disposable instance's browser session. For HTTPS deployments use the correct public URL and proxy configuration. |
| Ollama unexpectedly remains inactive | `LLM_PROVIDER` takes precedence over `AI_PROVIDER`; set both. Confirm the UI-selected provider and installed model tag. |
| Processing timeout or failed export | Inspect worker health and sanitized local logs; retry after cold startup. Keep the error visible. Do not disable isolation, increase production budgets, or label a draft a successful export. |
| Modern Sidebar cannot fit protected content | Use ATS Classic or edit content deliberately. Do not drop employment evidence just to force a one-page claim. |
| Job URL blocked / anti-bot page | Paste the actual offer and use copied-offer cleaning. Do not bypass SSRF/private-network checks. |
| Missing WeasyPrint/Chromium/native library in local Python | Prefer the existing containers; otherwise follow contributor setup including Playwright and native libraries. Do not add native parsers into the lean API image. |

Inspect `docker compose logs --tail=100 cv-tailor processor-owner browser-owner`
locally. Logs and configuration output may contain sensitive context: redact
before sharing. `/health` is a cheap liveness check, not a complete readiness or
real-model/export check.

## Stop and retain your data

```bash
docker compose down
```

This stops/removes this Compose stack's containers and network. The bind-mounted
`data/` remains. Do not run the command against another installation, prune Docker
globally or delete data as part of troubleshooting. To start again use
`docker compose up -d`; initialization is not rerun. The initial password is
hashed into `data/auth.json` on first start, so editing `APP_PASSWORD` later does
not reset it; use the existing authenticated password-change UI or
`docker compose exec cv-tailor python -m app.cli reset-password`.

For real personal data, first review [security](../SECURITY.md), backups, TLS and
[deployment](deployment.md). A shared public demo requires its own disposable
installation, isolated data/credentials/processors, quotas and an abuse/reset
policy. Do not expose an owner's instance or publish the local credentials.
The existing [recording launcher](recording-demo.md) loads a private account too;
it is not the fresh single-account walkthrough above or an anonymous SaaS sandbox.
