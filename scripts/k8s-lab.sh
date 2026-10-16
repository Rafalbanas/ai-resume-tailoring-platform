#!/usr/bin/env bash
set -euo pipefail

repo_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
lab_config="${CVTAILOR_LAB_KUBECONFIG:-${HOME}/.kube/cvtailor-lab.config}"
lab_context="kind-cvtailor-lab"

k() {
  kubectl --kubeconfig "$lab_config" --context "$lab_context" "$@"
}

case "${1:-}" in
  up)
    for tool in docker kind kubectl python3; do
      command -v "$tool" >/dev/null || { echo "Missing prerequisite: $tool" >&2; exit 1; }
    done
    cd "$repo_dir"
    docker build -t cvtailor:lab .
    mkdir -p "$(dirname -- "$lab_config")"
    if kind get clusters | grep -Fxq cvtailor-lab; then
      kind export kubeconfig --name cvtailor-lab --kubeconfig "$lab_config"
    else
      kind create cluster --name cvtailor-lab --config deploy/k8s/lab/kind.yaml \
        --kubeconfig "$lab_config" --wait 120s
    fi
    chmod 600 "$lab_config"
    kind load docker-image cvtailor:lab --name cvtailor-lab
    k apply -f deploy/k8s/lab/namespace.yaml
    # Keep first-run credentials stable on subsequent runs. Never read .env.
    existing_secret="$(k -n cvtailor-lab get secret cvtailor-secrets --ignore-not-found -o name)"
    if [[ -z "$existing_secret" ]]; then
      python3 - <<'PY' | k create -f -
import json
import secrets

print(json.dumps({
    "apiVersion": "v1", "kind": "Secret",
    "metadata": {"name": "cvtailor-secrets", "namespace": "cvtailor-lab"},
    "type": "Opaque",
    "stringData": {
        "APP_USERNAME": "student",
        "APP_PASSWORD": secrets.token_urlsafe(24),
        "CSRF_SECRET": secrets.token_urlsafe(48),
    },
}))
PY
    fi
    k apply -k deploy/k8s/lab
    # The fixed lab tag may have been rebuilt; restart even if YAML is unchanged.
    k -n cvtailor-lab rollout restart deployment/cvtailor
    k -n cvtailor-lab rollout status deployment/cvtailor --timeout=180s
    k -n cvtailor-lab get pods,svc,pvc
    echo "Ready. Run: bash scripts/k8s-lab.sh forward"
    ;;
  ai)
    exec "$repo_dir/.venv/bin/python" "$repo_dir/scripts/k8s-ai.py" enable
    ;;
  mock)
    exec "$repo_dir/.venv/bin/python" "$repo_dir/scripts/k8s-ai.py" mock
    ;;
  status)
    k -n cvtailor-lab get deployments,pods,svc,pvc
    ;;
  forward)
    exec kubectl --kubeconfig "$lab_config" --context "$lab_context" \
      -n cvtailor-lab port-forward --address 127.0.0.1 service/cvtailor 18080:8000
    ;;
  *)
    echo "Usage: bash scripts/k8s-lab.sh {up|status|forward|ai|mock}" >&2
    exit 1
    ;;
esac
