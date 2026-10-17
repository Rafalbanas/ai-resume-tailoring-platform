# Private and demo accounts at one address

Both accounts sign in at `https://cv.example.com/login` and use the same paths, including `/`, `/profile`, `/history` and downloads. There is no demo prefix or separate demo hostname. The account label shows the current login; fictional demo data also has a demo marker.

The public process loads two independent application runtimes. Each has its own Argon2id credential file, SQLite sessions, profile, skills, references, generated files, AI settings and task worker. The public session cookie contains an opaque ID and a server-signed account claim. The router checks the selected account's server-side session before dispatching to its runtime. URL parameters, headers, form fields and artifact IDs cannot select another runtime. The internal demo runtime has no network listener.

A browser context has one active account. Visiting `/login` starts a new sign-in and revokes its previous server-side session. Signing in to another account replaces that session for every tab. Old tabs cannot submit old CSRF tokens to the new account. Separate browser profiles or private windows can remain logged into different accounts at the same URL.

The same account can have concurrent sessions on multiple browsers and devices; tabs in one browser context share its session. **Sign out everywhere** revokes every session of the active account, without ending the other account's sessions. Already running requests or background jobs are not cancelled. Sessions also expire after an absolute eight hours by default (`SESSION_TTL_SECONDS=28800`); activity does not extend this deadline.

All UI pages use a nonce-based script CSP, template escaping, no-store responses and same-origin resource/opener policies. Confirmation dialogs use external JavaScript instead of inline handlers. Clipboard paste and password managers remain supported. Shared-origin accounts are not OS sandboxes: a server compromise or an exploitable script in this origin can affect the active account, as in other applications with a shared login. Do not treat demo credentials as authorization to execute arbitrary code.

## Configuration

Keep the existing private `DATA_DIR`, `BASE_URL`, `CSRF_SECRET` and private credentials. Add:

```dotenv
BASE_URL=https://cv.example.com
DEMO_DATA_DIR=/app/demo-data
# Optional: otherwise the demo's csrf.secret file is used.
DEMO_CSRF_SECRET_FILE=/run/cvtailor-demo/csrf-secret
```

`DEMO_DATA_DIR` must be a separate, non-overlapping directory with an existing demo `auth.json`, `master_profile.json` and `skills.json`. Login names must differ. `DEMO_CSRF_SECRET_FILE` must contain the existing independent demo CSRF secret; no plaintext passwords are copied. The application refuses invalid isolation or credential configuration. Neither blank nor default CSRF secrets are accepted. Without `DEMO_DATA_DIR`, existing single-account operation remains available.

To create a new fictional demo once:

```sh
.venv/bin/python scripts/recording_demo.py init
```

The command prints a randomly generated password once and refuses to overwrite an existing demo. It stores only an Argon2id hash. Keep the generated credentials privately. The default recording directory is `~/.local/share/cvtailor-recording-demo`; set `DEMO_DATA_DIR` to that directory for local use. The launcher `scripts/recording_demo.py run` starts the combined application on the configured main loopback port; stop existing services first so two workers never operate on the same data. It does not change provider models, timeouts or AI connection settings.

## Kubernetes migration

This repository prepares the configuration; it does not apply changes to live workloads or Nginx.

1. Back up both existing PVCs and configuration. Drain active private **and** demo tasks. Stop the old standalone demo deployment before starting the combined process so there is only one worker per account.
2. Build the patched main image. The updated resources mount `cvtailor-demo-data` at `/app/demo-data` in the main pod and mount only `CSRF_SECRET` from `cvtailor-demo-runtime` at `/run/cvtailor-demo/csrf-secret`. Preserve independent PVC contents and existing login names/password hashes. The old demo deployment is kept at zero replicas for rollback; no data migration or password reset is required.
3. Apply the updated main ConfigMap, volumes and deployment. Set the public `BASE_URL` accurately. Use the standard loopback proxy for all account requests. Remove the old `/demo/` upstream to port 18001 from the private Nginx virtual host. No DNS or certificate change is required.
4. Optionally preserve old bookmarks with these blocks in the same HTTPS virtual host (already included in the repository example):

   ```nginx
   location = /demo { return 302 /login; }
   location ^~ /demo/ { return 302 /login; }
   ```

   A 302 moves old forms to a fresh login instead of forwarding their body to another endpoint.
5. Validate and reload Nginx, roll out the patched image and check both credentials at `/login`. Existing cookies are invalidated by the new signing scheme: sign in again. Check account labels, profile, uploads, history, downloads, task polling and password changes separately. The monitor now follows declared replica counts and the common `/health`; startup of the public app includes both runtimes. Deploy drain and backup continue checking both task directories.
6. Install the updated deployment wrapper and monitor script alongside the Kubernetes change. CI's ordinary image rollout does not automatically apply new ConfigMap keys, mounts or Nginx locations. For rollback, stop the combined pod before restoring separate workers and the old routing/configuration; retain both PVCs and secrets.

Standalone recording mode is retained for compatibility and tests; when separately exposed, it must use an independent hostname. It is not the shared-login deployment described here.
