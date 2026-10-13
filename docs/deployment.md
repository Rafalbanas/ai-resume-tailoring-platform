# VPS deployment

1. Create a deployment directory on the VPS and clone/copy the repository.
2. Copy `.env.example` to `.env` and use unique random secrets. The production defaults select `AI_PROVIDER=ollama`, `OLLAMA_BASE_URL=http://127.0.0.1:11434`, and `OLLAMA_MODEL=qwen3.5:9b`.
3. Copy `data/master_profile.example.json` to `data/master_profile.json`, then replace all fictional values with verified candidate facts.
4. Install/start Ollama on the host, pull `qwen3.5:9b`, and verify `curl http://127.0.0.1:11434/api/tags`.
5. Run `docker compose up -d --build` and verify both `/health` and `/health/provider` on `127.0.0.1:$CV_TAILOR_PORT` (port `8000` by default).
6. Configure the existing reverse proxy so your HTTPS hostname forwards to `http://127.0.0.1:8000` and preserves `Host`/forwarded headers. A sanitized example is provided in `deploy/nginx/cv.example.com.conf`.
7. Terminate TLS at the reverse proxy. Compose uses host networking so the container can reach host-loopback Ollama, while Uvicorn itself remains bound to loopback.
8. Back up the `data/` directory; it contains the master profile and generated applications.
9. Upload private reference CVs through the authenticated **Reference CVs** screen. Optionally upload a candidate photo through the **Profile** screen or place it under `data/profile_photo/`. Neither path is included in Git or the Docker image.

CI checks pull requests and pushes. Production deployment is a separate manually triggered CD workflow, described below.

## Continuous deployment from GitHub Actions

`Deploy CVTailor` is initially **manual**, via Actions → Deploy CVTailor → Run workflow → `main`. It runs the full CI checks, checks that the running commit is an ancestor of the release, publishes an image to GHCR, then deploys its immutable digest over restricted SSH. Merge all feature PRs already deployed on the VPS into `main` before the first release (a merged stacked PR may only be present on its parent branch): the ancestry check prevents accidental downgrades. No PRs are automatically merged.

The workflow forwards its short-lived `GITHUB_TOKEN` over SSH stdin for the registry pull. Docker credentials are held in a temporary directory and removed on success or failure; no permanent registry token is required on the VPS. Application secrets and private data stay on the VPS.

### One-time server setup

Install the reviewed `deploy/cd/deploy.sh` as root-owned `/usr/local/sbin/cvtailor-deploy`, and `deploy/cd/ssh-command.sh` as root-owned `/usr/local/bin/cvtailor-cd-ssh`. Neither is automatically overwritten by a release. Create a dedicated `cvtailor-deploy` account with no Docker group membership. Its authorized key must use:

```text
restrict,command="/usr/local/bin/cvtailor-cd-ssh" ssh-ed25519 YOUR_PUBLIC_KEY
```

Allow that account to run only the root deployment script via `/etc/sudoers.d/cvtailor-cd`:

```text
cvtailor-deploy ALL=(root) NOPASSWD: /usr/local/sbin/cvtailor-deploy
```

Validate sudoers with `visudo -cf`. The forced SSH command accepts only `status` or `deploy FULL_COMMIT_SHA sha256:FULL_DIGEST`. The root script validates all arguments again and uses a fixed repository and server paths from root-owned `/etc/cvtailor/deploy.env` (mode 600):

```bash
APP_DIR=/root/ai-resume-tailoring-platform
COMPOSE_FILE=/root/ai-resume-tailoring-platform/docker-compose.yml
STATE_DIR=/var/lib/cvtailor-cd
CONTAINER=cv-tailor
SERVICE=cv-tailor
IMAGE_REPOSITORY=ghcr.io/rafalbanas/ai-resume-tailoring-platform
REGISTRY_USER=rafalbanas
HEALTH_URL=http://127.0.0.1:18000/health
```

Use your actual paths and loopback port. Keep `.env` and `data/` in `APP_DIR`. The script uses the existing Compose configuration and an image-only override, preserving host networking, Ollama, demo routing, and private storage.

Configure repository secrets: `VPS_HOST`, `VPS_PORT`, `VPS_USER`, `VPS_SSH_KEY`, and `VPS_KNOWN_HOSTS`. Obtain the SSH host key directly from the server's `/etc/ssh/ssh_host_ed25519_key.pub`; do not trust an unverified scan. For a non-default port, the known-hosts entry starts with `[hostname]:port`. Restrict the `production` GitHub environment to `main`.

`Check VPS deployment connection` performs a read-only check from a GitHub runner and verifies that arbitrary SSH commands are rejected. It does not rebuild or restart the application.

### Release behavior and rollback

Deployments are serialized in Actions and by a server file lock. Active queued/running analyses block deployment both before and after pulling the image. A release uses `up -d --no-build --pull never`, verifies the image revision, polls the loopback health endpoint for up to approximately 60 seconds, and verifies the running revision. There is a brief interruption when the single container is recreated. Health checks do not make external AI calls.

On deployment failure the script recreates the previous image and checks its health, then returns failure to Actions. This restores code, not private data; deployments never remove volumes. Changes needing data migrations require a separate reviewed migration and backup plan.

After success `/var/lib/cvtailor-cd/current.yml` contains the digest pinned image and `previous-image` contains the previous image ID. Future manual Compose restarts must include `-f /var/lib/cvtailor-cd/current.yml` to retain the deployed version. Do not prune the previous image until the new release has been verified.

To enable automatic CD later, add `push: {branches: [main]}` alongside `workflow_dispatch` in `cd.yml`. The existing `needs: test` still blocks deployment if tests fail. Start with one successful manual release first.
