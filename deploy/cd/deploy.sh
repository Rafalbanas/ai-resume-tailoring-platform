#!/usr/bin/env bash
set -Eeuo pipefail
export PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
# Only root-owned configuration is used in production; override is for isolated tests.
source "${CVTAILOR_DEPLOY_CONFIG:-/etc/cvtailor/deploy.env}"
if [[ ${1:-} == status && $# == 1 ]]; then
    docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CONTAINER"
    exit
fi
[[ $# == 2 && $1 =~ ^[a-f0-9]{40}$ && $2 =~ ^sha256:[a-f0-9]{64}$ ]] || { echo 'Invalid revision or image digest.' >&2; exit 2; }
revision=$1
image="$IMAGE_REPOSITORY@$2"
mkdir -p "$STATE_DIR"
exec 9>"$STATE_DIR/deploy.lock"
flock -n 9 || { echo 'Another deployment is running.' >&2; exit 1; }
active_tasks() {
    docker exec "$CONTAINER" python -c 'import json,pathlib; n=sum(json.loads(p.read_text()).get("status") in ("running","queued") for p in pathlib.Path("/app/data/tasks").glob("*.json")); print("Active analyses:", n); raise SystemExit(1 if n else 0)'
}
active_tasks
previous=$(docker inspect --format '{{.Image}}' "$CONTAINER")
previous_sha=$(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CONTAINER")
export DOCKER_CONFIG
DOCKER_CONFIG=$(mktemp -d)
override=$(mktemp "$STATE_DIR/override.XXXXXX.yml")
changed=false
healthy() {
    for ((attempt=0; attempt<30; attempt++)); do
        if curl --max-time 3 -fsS "$HEALTH_URL" >/dev/null; then return 0; fi
        sleep 2
    done
    return 1
}
compose_up() {
    APP_BUILD_SHA="$1" APP_BUILD_TIMESTAMP="$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
        docker compose --project-directory "$APP_DIR" -f "$COMPOSE_FILE" -f "$override" \
        --env-file "$APP_DIR/.env" up -d --no-build --pull never "$SERVICE"
}
cleanup() {
    code=$?
    trap - EXIT
    if [[ $code != 0 && $changed == true ]]; then
        echo 'Deployment failed; restoring the previous image.' >&2
        printf 'services:\n  %s:\n    image: %s\n' "$SERVICE" "$previous" > "$override"
        if compose_up "$previous_sha" && healthy; then
            echo 'Previous image restored.' >&2
        else
            echo 'ROLLBACK FAILED: manual intervention required.' >&2
        fi
    fi
    rm -rf "$DOCKER_CONFIG"
    rm -f "$override"
    exit "$code"
}
trap cleanup EXIT
# The workflow token arrives over stdin; it is never persisted beyond this invocation.
docker login ghcr.io --username "$REGISTRY_USER" --password-stdin >/dev/null
docker pull "$image"
actual=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image")
[[ $actual == "$revision" ]] || { echo 'Image revision does not match requested commit.' >&2; exit 1; }
active_tasks
printf 'services:\n  %s:\n    image: %s\n' "$SERVICE" "$image" > "$override"
changed=true
compose_up "$revision"
healthy
[[ $(docker inspect --format '{{.State.Running}}' "$CONTAINER") == true ]]
[[ $(docker inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$CONTAINER") == "$revision" ]]
printf 'services:\n  %s:\n    image: %s\n' "$SERVICE" "$image" > "$STATE_DIR/current.yml.tmp"
mv "$STATE_DIR/current.yml.tmp" "$STATE_DIR/current.yml"
printf '%s\n' "$previous" > "$STATE_DIR/previous-image"
echo "Deployed $revision successfully."
