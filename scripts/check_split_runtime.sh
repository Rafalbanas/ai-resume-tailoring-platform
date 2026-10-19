#!/bin/sh
# Isolated local/CI integration check; no production containers, ports or volumes.
set -eu
check_suffix="$$"
check_network="cvtailor-check-$check_suffix"
check_documents="cvtailor-documents-$check_suffix"
check_browser="cvtailor-browser-$check_suffix"
cleanup() {
    check_exit=$?
    if [ "$check_exit" -ne 0 ]; then
        docker logs "$check_documents" 2>&1 || true
        docker logs "$check_browser" 2>&1 || true
    fi
    docker rm -f "$check_documents" "$check_browser" >/dev/null 2>&1 || true
    docker network rm "$check_network" >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

docker network create --internal "$check_network" >/dev/null
for check_role in documents browser; do
    if [ "$check_role" = documents ]; then
        check_name="$check_documents"
        check_token="synthetic-document-token-for-isolated-image-check"
    else
        check_name="$check_browser"
        check_token="synthetic-browser-token-for-isolated-image-check"
    fi
    docker run --detach --name "$check_name" --network "$check_network" --network-alias "$check_role" \
        --read-only --tmpfs /tmp:size=256m,mode=1777 --cap-drop ALL --security-opt no-new-privileges \
        --memory 768m --pids-limit 128 \
        --env "PROCESSING_TOKEN=$check_token" --env PROCESSING_CONTAINER_ISOLATED=1 \
        "cvtailor:split-$check_role" >/dev/null
    check_attempt=0
    until docker exec "$check_name" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')" >/dev/null 2>&1; do
        check_attempt=$((check_attempt + 1))
        if [ "$check_attempt" -ge 30 ]; then
            docker logs "$check_name"
            exit 1
        fi
        sleep 1
    done
done

docker run --rm --network "$check_network" --user 10001:10001 --read-only \
    --tmpfs /tmp:size=256m,mode=1777 --cap-drop ALL --security-opt no-new-privileges \
    --env PROCESSING_URL=http://documents:8080 \
    --env PROCESSING_TOKEN=synthetic-document-token-for-isolated-image-check \
    --env BROWSER_PROCESSING_URL=http://browser:8080 \
    --env BROWSER_PROCESSING_TOKEN=synthetic-browser-token-for-isolated-image-check \
    --entrypoint python cvtailor:split-api -m scripts.check_runtime_image api --rpc
