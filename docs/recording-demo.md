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

Open https://cv.banas.dev/demo/login. The main account remains at https://cv.banas.dev/login. Nginx routes only `/demo/` to the separate loopback listener and strips that prefix; the demo runs with root_path `/demo`. No DNS or Cloudflare changes are needed. Cookies are named `demo_session` and `demo_csrf_token` and scoped to `/demo`, so logout does not affect the main account. The demo still requires its owner credentials; no public demo account was added.

All fictional data, hashed credentials, sessions and the automatic fallback setting live under `/root/.local/share/cvtailor-recording-demo`. The existing `.env` supplies AI connection settings directly; the launcher overrides data directory, credentials, CSRF, profile mode and base URL in memory. It never copies production profile files. It fixes the first provider to Ollama. Model names, generation parameters, provider timeouts and retry settings remain as configured.

Stop the deployed demo with `systemctl stop cvtailor-recording-demo`. To remove it permanently, run `systemctl disable --now cvtailor-recording-demo`, remove only the two `/demo` locations from `/etc/nginx/sites-available/cv.banas.dev.conf`, validate with `nginx -t` and reload Nginx. Then delete only `/root/.local/share/cvtailor-recording-demo` and `/etc/systemd/system/cvtailor-recording-demo.service`, followed by `systemctl daemon-reload`. Leave the main `/` proxy location, repository `data/`, `.env` and the cv-tailor container untouched. A copy of the original proxy configuration is at `/etc/nginx/sites-available/cv.banas.dev.before-demo`.

Automatic fallback defaults on, is stored in each instance's `ai_settings.json`, and is editable only by the authenticated owner. Auto and Ollama use Ollama → Gemini; Gemini uses Gemini → Ollama. With fallback off, only the first provider is called. Gemini may still be selected manually and sends analysis inputs to Google's API. Results report the actual provider/model and fallback status. Existing mock/n8n runtime support is retained for tests and integrations.

This is intended for private recording; no public-demo or prompt-injection security assessment is claimed. Restarting or updating the private instance is a separate deployment step.
