# Private recording demo

This remains a single-owner application. Login uses Starlette's signed session-cookie mechanism carrying only an opaque ID, backed by a server-revocable SQLite session (8 hours), HttpOnly and SameSite=Strict cookies, Secure when BASE_URL is HTTPS, signed double-submit CSRF validation and a five-attempt / five-minute login limit per client address. Existing auth.json Argon2id credentials are retained. Password changes invalidate existing sessions. HTTP Basic credentials no longer authenticate requests. Only static assets, the login page and the minimal health probe are public. Keep reverse proxies free of auth_basic; the repository's nginx configuration has none. Trust proxy headers only from the actual loopback proxy, not arbitrary addresses.

Initialize once from the repository root:

```sh
.venv/bin/python scripts/recording_demo.py init
```

Initialization prints a new random password once; save it privately. It never writes plaintext passwords. Do not rerun initialization over an existing demo.

The deployed demo is managed by systemd:

```sh
systemctl start cvtailor-recording-demo
```

For manual development, first stop the service to free its listener, then start from the repository root:

```sh
.venv/bin/python scripts/recording_demo.py run
```

Open `https://cv.example.com/demo/login`. The main account remains at `https://cv.example.com/login`. Nginx routes only `/demo/` to the separate loopback listener and strips that prefix; the demo runs with root_path `/demo`. Cookies are named `demo_session` and `demo_csrf_token` and scoped to `/demo`, so logout does not affect the main account. The demo still requires its generated owner credentials; no unauthenticated public demo account is provided.

All fictional data, hashed credentials, sessions and the automatic fallback setting live under an isolated demo data directory (`~/.local/share/cvtailor-recording-demo`). The existing `.env` supplies AI connection settings directly; the launcher overrides data directory, credentials, CSRF, profile mode and base URL in memory. It never copies production profile files. It fixes the initial provider to Ollama. Model names, generation parameters, provider timeouts and retry settings remain as configured.

Stop the deployed demo service with `systemctl stop cvtailor-recording-demo`. To remove it permanently, disable the service, remove the `/demo` location blocks from the reverse proxy configuration, validate and reload Nginx, then delete the demo data directory and systemd unit. Leave the main `/` proxy location, repository `data/`, `.env` and the primary cv-tailor container untouched.

Automatic fallback defaults on, is stored in each instance's `ai_settings.json`, and is editable only by the authenticated owner. Auto and Ollama use Ollama → Gemini; Gemini uses Gemini → Ollama. With fallback off, only the first provider is called. Gemini may still be selected manually and sends analysis inputs to Google's API. Results report the actual provider/model and fallback status. Existing mock/n8n runtime support is retained for tests and integrations.

This is intended for private recording; no public-demo or prompt-injection security assessment is claimed. Restarting or updating the private instance is a separate deployment step.
