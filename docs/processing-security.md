# Bounded and isolated processing

The web process admits requests and selects the authenticated account. PDF/DOCX extraction, document export, preview rasterization and photo decoding run in disposable processes, not the web event loop. Production uses **independent processing services for owner and demo**. Neither receives account PVCs, `.env`, AI keys, login credentials, session databases or a Kubernetes service account token. A job receives only its required profile/document snapshot in a temporary directory, which is removed after the child exits.

## Enforced budgets

| Resource | Default limit |
|---|---|
| Regular request body | 512 KiB, including chunked requests |
| Upload request body | 12 MiB total, at most 20 files / 200 fields |
| Authentication body | Existing 16 KiB limit |
| Total body reception | 15 seconds authentication, 30 seconds regular forms, 60 seconds uploads/internal RPC; small periodic chunks do not reset the deadline |
| Concurrent request bodies | 2 shared by both accounts |
| Concurrent account changes | 1 per account; reads and logout remain available |
| Native document processing | 1 admitted operation per account, at most 2 isolated production workers; demo cannot occupy the owner’s reserved slot |
| Native child | 768 MiB address space, 45 CPU seconds, 60-second wall deadline, 12 MiB output file limit |
| Reference parser | 20-second wall deadline, 30 PDF pages, 250,000 text characters, 8 MB decoded PDF content / stream, 16 MB filter work per stream |
| Reference library | 20 documents and 100 MB total |
| Chromium | 1 active render per account (worker admits only one browser/document job at once); 32 routed requests, 4× configured fetch-byte budget, whole-render deadline |
| Active AI calls | 1 shared by both accounts |
| Durable AI request budget | 300 owner / 60 demo calls per UTC day, including retries and semantic review; does not reset on restart |
| AI response | 2 MiB uncompressed; compressed responses rejected; Gemini output capped at 8192 tokens; total exchange limited by the configured read timeout (300 seconds if disabled) |
| Task admission | 4 queued/running tasks per account, checked under a cross-process file lock |
| Task retention | Latest 100 task records; active work is never pruned |
| Account storage | 512 MiB owner / 128 MiB demo admission quota; 64 MiB reserved for bounded in-flight output; 10,000 file/directory entries |
| Preview cache | 2 entries per account, up to 8 MiB each, keyed by the resume, profile, layout and photo |

`MAX_PENDING_TASKS`, `AI_DAILY_CALL_LIMIT`, `DEMO_AI_DAILY_CALL_LIMIT`, `STORAGE_QUOTA_BYTES` and `DEMO_STORAGE_QUOTA_BYTES` configure account budgets. The daily request budget is not a currency meter; provider pricing and hidden work in an operator-modified n8n workflow remain outside this application. No generated CV is automatically deleted. Old task records and orphan analysis drafts associated with pruned tasks are removed; drafts linked to saved CVs remain. Cleanup and logout work even when storage admission is exhausted.

The storage quota is an admission limit with bounded output headroom, not a filesystem quota. Existing data over the quota stays intact and may be downloaded or deleted. Snapshots and backups outside the account directory are managed by deployment operations.

## Native-process boundary

A child has a clean environment and uses a process group. Timeout or exit kills descendants and releases admission. The isolated processor runs as container PID 1 and also kills/reaps any leftover processes in its own PID namespace, including Chromium sessions detached by Playwright; local CLI mode never enumerates unrelated processes. Failed output cannot overwrite a reviewed CV. The worker protocol is a fixed set of JSON operations, never pickle or arbitrary Python functions. Parser error details are not returned to users. The worker service authenticates before reading its request body, uses a distinct random token for each account and refuses to start without one.

Linux libseccomp blocks IPv4/IPv6/netlink sockets, ptrace, cross-process memory access and selected escape-related syscalls in native document children. Chromium inherits the same socket restriction from its launcher: it cannot connect directly even if a Playwright interception were missed. Validated HTTP(S) is fetched by the trusted Python transport and fulfilled into Chromium. Browser env excludes application secrets, service workers and WebSockets remain blocked, and redirect/IP checks remain in force. Chromium's own `--no-sandbox` compatibility setting is therefore supplemented by this external kernel policy and, in production, a separate container/pod without account files. Failure to load the policy fails processing closed.

Local Python/CLI usage without `PROCESSING_URL` uses disposable bounded subprocesses on the same filesystem; it does **not** provide the separate filesystem/PID namespace of production. Use isolated services for untrusted users. `PROCESSING_REQUIRED=true` forbids silently falling back to local processing. A configured service that is unavailable never falls back to the application process.

## Docker Compose

Generate a random `PROCESSING_TOKEN` (at least 32 characters) in `.env` before `docker compose up --build`. For shared demo also generate a different `DEMO_PROCESSING_TOKEN` and start with `--profile demo`, in addition to the existing demo data/CSRF mounts. Never reuse the login/CSRF/Gemini secrets.

The web container retains host networking for the local Ollama connection. Processors use an ordinary Docker network, no data volumes, a read-only root filesystem, temporary scratch storage, non-root UID, dropped capabilities, 768 MiB memory and 128-process limits. Only their authenticated API is published, on loopback ports 18002/18003. Worker containers receive only their own processing token. They do not use the application's `.env` file.

## Kubernetes migration

This is a one-time deployment migration, not an image-only configuration change. Back up the application first. Build/publish the reviewed image and use its exact GHCR digest; the old pre-worker image cannot start these services.

From the reviewed checkout, as the cluster administrator:

```bash
sudo python3 deploy/k8s/production/install-processing.py \
  ghcr.io/rafalbanas/ai-resume-tailoring-platform@sha256:REPLACE_WITH_REVIEWED_DIGEST
sudo install -m 755 deploy/k8s/production/deploy.py /usr/local/sbin/cvtailor-deploy
sudo install -m 755 deploy/k8s/production/operations.py /usr/local/sbin/cvtailor-operations
```

The installer drains mutations and both AI queues using the existing deployment lock, creates independent random service tokens without printing them or storing them in an apply annotation, installs the two worker Deployments, ClusterIP Services and NetworkPolicies, waits for readiness, and only then enables their URLs/tokens in the main deployment. No profile, password or CV migration occurs. It is idempotent and preserves existing tokens. Keep the checkout root-owned while running an administrator script.

`processing.json` deliberately has an invalid image placeholder: the installer replaces it with the supplied digest before applying. It must not be applied directly. Worker pods use ordinary pod networking, independent PID/filesystem namespaces, no PVCs or API tokens, read-only root filesystems, bounded scratch storage and separate cgroups. Egress policy allows cluster DNS and public TCP 80/443, excluding private, loopback, link-local and metadata ranges; there is no IPv6 egress allowance. NetworkPolicy requires an enforcing CNI. Node-origin ingress handling is CNI-specific, so authentication remains mandatory. The native socket filter independently blocks browser/parser traffic, even on platforms where NetworkPolicy behavior differs.

After the migration, the updated deployment wrapper updates existing processor Deployments to the validated application digest before releasing the web image, and restores their previous image on release failure. Monitoring includes the workers. Backups use SQLite's backup API for the durable resource budget database as well as sessions. Perform one synthetic upload/export for each account and check the worker pods after rollout. The main app's public health endpoint intentionally remains a cheap liveness check, independent of a long-running parser.

For rollback, restore the previous application and processor image digests together. Do not delete PVCs or change credentials. Older pre-worker application versions ignore the extra service settings; retain the worker resources until the rollback is verified. Increasing budgets or disabling isolation is an operator decision; no user-supplied URL, form field or model output can select a worker or alter these settings.

## AI boundary

No new tools or server secrets are exposed to the model. Existing prompt-injection tests now also cover processing-service secrets. Real model HTTP calls are serialized and charged before sending; oversized or compressed responses fail before JSON parsing. Prompt/schema compliance is not used to enforce time, memory, response or call limits. This hardens availability and costs; it does not promise universal model-level jailbreak resistance or make LLM semantic review a proof of factual correctness.

## References

- [Python resource limits](https://docs.python.org/3.14/library/resource.html)
- [Kubernetes NetworkPolicy requirements and CNI behavior](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
