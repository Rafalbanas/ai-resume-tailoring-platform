"""Controlled integration scenarios for the existing cvtailor-lab only."""

import argparse
import copy
import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / ".k8s-lab/e2e"
CLI = ["kubectl", "--kubeconfig", os.environ.get("CVTAILOR_LAB_KUBECONFIG", str(Path.home() / ".kube/cvtailor-lab.config")), "--context", "kind-cvtailor-lab", "-n", "cvtailor-lab"]


def k(*args, payload=None):
    result = subprocess.run(CLI + list(args), input=payload, text=True, capture_output=True, timeout=210)
    if result.returncode:
        raise RuntimeError(result.stderr.strip()[:1500])
    return result.stdout.strip()


def obj(*args):
    return json.loads(k(*args, "-o", "json"))


def pod_code(code, target="deployment/cvtailor"):
    return k("exec", target, "--", "python", "-c", code)


def http(mode, label, *args, target="deployment/cvtailor"):
    source = (ROOT / "scripts/k8s-e2e-http.py").read_text()
    result = subprocess.run(CLI + ["exec", "-i", target, "--", "python", "-u", "-", mode, label, *args], input=source, text=True, timeout=1100)
    if result.returncode:
        raise RuntimeError("HTTP scenario failed: " + label)
    return json.loads(pod_code(f"from pathlib import Path; print(Path('/lab-data/.e2e/{label}.json').read_text())", target))


def restart():
    print(k("rollout", "restart", "deployment/cvtailor"), flush=True)
    print(k("rollout", "status", "deployment/cvtailor", "--timeout=180s"), flush=True)


def patch_config(data):
    k("patch", "configmap", "cvtailor-config", "--type=merge", "--patch-file=/dev/stdin", payload=json.dumps({"data": data}))


def task(task_id):
    return json.loads(pod_code(f"from pathlib import Path; print(Path('/lab-data/tasks/{task_id}.json').read_text())"))


def fault_test(both=False):
    old = obj("get", "configmap", "cvtailor-config")["data"]
    changes = {"OLLAMA_BASE_URL": "http://127.0.0.1:9", "OLLAMA_CONNECT_TIMEOUT_SECONDS": "2"}
    if both:
        changes.update(GEMINI_BASE_URL="http://127.0.0.1:9", GEMINI_CONNECT_TIMEOUT_SECONDS="2")
    try:
        patch_config(changes)
        restart()
        if both:
            return http("fail", "both-unavailable")
        return http("generate", "fallback-e2e", "--expected-provider", "gemini", "--fallback", "true")
    finally:
        patch_config({name: old.get(name) for name in changes})
        restart()
        assert obj("get", "configmap", "cvtailor-config")["data"] == old


def crash_test():
    record = http("submit", "interrupted-e2e", "--provider", "ollama")
    task_id = record["task_id"]
    for _ in range(25):
        current = task(task_id)
        if current["status"] == "running":
            break
        time.sleep(1)
    assert current["status"] == "running"
    pods = obj("get", "pods", "-l", "app=cvtailor")["items"]
    pod = next(p for p in pods if not p["metadata"].get("deletionTimestamp"))
    name, uid = pod["metadata"]["name"], pod["metadata"]["uid"]
    count = pod["status"]["containerStatuses"][0]["restartCount"]
    print("Crashing lab application while task is running: " + task_id, flush=True)
    container_id = pod["status"]["containerStatuses"][0]["containerID"].removeprefix("containerd://")
    assert len(container_id) == 64 and all(c in "0123456789abcdef" for c in container_id)
    node = pod["spec"]["nodeName"]
    assert node == "cvtailor-lab-control-plane"
    subprocess.run(["docker", "exec", node, "ctr", "--namespace", "k8s.io", "tasks", "kill", "--signal", "SIGKILL", container_id], capture_output=True, timeout=20, check=True)
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        fresh = obj("get", "pod", name)
        status = fresh.get("status", {}).get("containerStatuses", [{}])[0]
        if status.get("restartCount", 0) > count and status.get("ready"):
            break
        time.sleep(2)
    else:
        raise RuntimeError("Application did not recover from the test crash")
    assert fresh["metadata"]["uid"] == uid
    interrupted = task(task_id)
    assert interrupted["status"] == "failed" and "restart" in interrupted["error"].lower()
    http("inspect", "interrupted-visible", "--task-id", task_id)
    retried = http("retry", "retry-e2e", "--task-id", task_id, "--expected-provider", "ollama", "--fallback", "false")
    assert retried["task_id"] != task_id
    assert task(task_id)["status"] == "failed"
    return {"interrupted_task": task_id, "retry": retried, "same_pod_recovered": True}


def create(resource):
    return json.loads(k("create", "-f", "-", "-o", "json", payload=json.dumps(resource)))


def wait_ready(name):
    print(k("wait", "--for=condition=Ready", "pod/" + name, "--timeout=120s"), flush=True)


def backup_test():
    deployment = obj("get", "deployment", "cvtailor")
    spec = deployment["spec"]["template"]["spec"]
    volumes = spec["volumes"]
    source_claim = next(v["persistentVolumeClaim"]["claimName"] for v in volumes if v["name"] == "data")
    for kind, name in [("pod", "e2e-backup-reader"), ("pod", "e2e-restore-writer"), ("pod", "e2e-restored-app"), ("pvc", "e2e-restored-data")]:
        assert not k("get", kind, name, "--ignore-not-found", "-o", "name"), "Test resource already exists: " + name
    unfinished = pod_code("import json; from pathlib import Path; print(sum(json.loads(p.read_text()).get('status') in ('running','queued') for p in Path('/lab-data/tasks').glob('*.json')))")
    assert unfinished == "0"
    made = []

    def helper(name, claim):
        return {"apiVersion": "v1", "kind": "Pod", "metadata": {"name": name, "namespace": "cvtailor-lab", "labels": {"e2e": "restore"}}, "spec": {
            "automountServiceAccountToken": False, "restartPolicy": "Never", "terminationGracePeriodSeconds": 1,
            "securityContext": {"runAsNonRoot": True, "runAsUser": 10001, "runAsGroup": 10001, "fsGroup": 10001},
            "containers": [{"name": "helper", "image": spec["containers"][0]["image"], "imagePullPolicy": "Never", "command": ["python", "-c", "import time; time.sleep(1800)"],
                            "resources": {"requests": {"cpu": "10m", "memory": "16Mi"}, "limits": {"cpu": "100m", "memory": "128Mi"}},
                            "securityContext": {"allowPrivilegeEscalation": False, "capabilities": {"drop": ["ALL"]}}, "volumeMounts": [{"name": "data", "mountPath": "/lab-data"}]}],
            "volumes": [{"name": "data", "persistentVolumeClaim": {"claimName": claim}}]}}

    def track(resource):
        created = create(resource)
        made.append((resource["kind"].lower(), resource["metadata"]["name"], created["metadata"]["uid"]))

    hashes_code = "import hashlib,json; from pathlib import Path; root=Path('/lab-data'); print(json.dumps({str(p.relative_to(root)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob('*')) if p.is_file()}))"
    try:
        k("scale", "deployment/cvtailor", "--replicas=0")
        deadline = time.monotonic() + 120
        while obj("get", "pods", "-l", "app=cvtailor")["items"]:
            assert time.monotonic() < deadline, "Application did not stop for consistent backup"
            time.sleep(2)
        track(helper("e2e-backup-reader", source_claim))
        wait_ready("e2e-backup-reader")
        original_hashes = json.loads(pod_code(hashes_code, "e2e-backup-reader"))
        backup = OUT / ("lab-data-" + time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + ".tar.gz")
        with os.fdopen(os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "wb") as output:
            result = subprocess.run(CLI + ["exec", "e2e-backup-reader", "--", "python", "-c", "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdout.buffer,mode='w|gz'); archive.add('/lab-data',arcname='.'); archive.close()"], stdout=output, stderr=subprocess.PIPE, timeout=120)
            assert result.returncode == 0, "Backup archive creation failed"
        track({"apiVersion": "v1", "kind": "PersistentVolumeClaim", "metadata": {"name": "e2e-restored-data", "namespace": "cvtailor-lab"}, "spec": {"accessModes": ["ReadWriteOnce"], "storageClassName": "standard", "resources": {"requests": {"storage": "1Gi"}}}})
        track(helper("e2e-restore-writer", "e2e-restored-data"))
        wait_ready("e2e-restore-writer")
        with backup.open("rb") as source:
            result = subprocess.run(CLI + ["exec", "-i", "e2e-restore-writer", "--", "python", "-c", "import sys,tarfile; archive=tarfile.open(fileobj=sys.stdin.buffer,mode='r|gz'); archive.extractall('/lab-data',filter='data')"], stdin=source, capture_output=True, timeout=120)
            assert result.returncode == 0, "Backup extraction failed"
        restored_hashes = json.loads(pod_code(hashes_code, "e2e-restore-writer"))
        assert restored_hashes == original_hashes, "Restored file hashes differ"
        k("delete", "pod", "e2e-restore-writer", "--wait=true", "--timeout=60s")
        restored_spec = copy.deepcopy(spec)
        next(v for v in restored_spec["volumes"] if v["name"] == "data")["persistentVolumeClaim"]["claimName"] = "e2e-restored-data"
        track({"apiVersion": "v1", "kind": "Pod", "metadata": {"name": "e2e-restored-app", "namespace": "cvtailor-lab", "labels": {"e2e": "restore"}}, "spec": restored_spec})
        wait_ready("e2e-restored-app")
        verified = http("artifacts", "restored-downloads", target="e2e-restored-app")
        return {"files_verified": len(original_hashes), "backup": str(backup), "sha256": hashlib.sha256(backup.read_bytes()).hexdigest(), "restored_http": verified}
    finally:
        for kind, name, uid in reversed(made):
            resource = k("get", kind, name, "--ignore-not-found", "-o", "json")
            if resource:
                assert json.loads(resource)["metadata"]["uid"] == uid
                k("delete", kind, name, "--wait=true", "--timeout=90s")
        k("scale", "deployment/cvtailor", "--replicas=" + str(deployment["spec"]["replicas"]))
        print(k("rollout", "status", "deployment/cvtailor", "--timeout=180s"), flush=True)


def image_test():
    before = obj("get", "deployment", "cvtailor")
    revision = before["metadata"]["annotations"]["deployment.kubernetes.io/revision"]
    original = before["spec"]["template"]["spec"]["containers"][0]["image"]
    pods = obj("get", "pods", "-l", "app=cvtailor")["items"]
    original_id = next(p for p in pods if not p["metadata"].get("deletionTimestamp"))["status"]["containerStatuses"][0]["imageID"]
    expected = "cvtailor:lab-e2e-v2"
    try:
        print(k("set", "image", "deployment/cvtailor", "app=" + expected), flush=True)
        print(k("rollout", "status", "deployment/cvtailor", "--timeout=180s"), flush=True)
        marker = pod_code("import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/static/kubernetes-release.txt').read().decode().strip())")
        assert marker == "kubernetes-e2e-v2"
        pods = obj("get", "pods", "-l", "app=cvtailor")["items"]
        image_id = next(p for p in pods if not p["metadata"].get("deletionTimestamp"))["status"]["containerStatuses"][0]["imageID"]
        assert image_id != original_id, "Runtime image ID did not change"
        print("New release marker served over HTTP; imageID=" + image_id, flush=True)
    finally:
        print(k("rollout", "undo", "deployment/cvtailor", "--to-revision=" + revision), flush=True)
        print(k("rollout", "status", "deployment/cvtailor", "--timeout=180s"), flush=True)
        assert obj("get", "deployment", "cvtailor")["spec"]["template"] == before["spec"]["template"]
    code = "import urllib.request, urllib.error\ntry:\n urllib.request.urlopen('http://127.0.0.1:8000/static/kubernetes-release.txt')\nexcept urllib.error.HTTPError as e:\n print(e.code)"
    assert pod_code(code) == "404"
    restored_pods = obj("get", "pods", "-l", "app=cvtailor")["items"]
    restored_id = next(p for p in restored_pods if not p["metadata"].get("deletionTimestamp"))["status"]["containerStatuses"][0]["imageID"]
    assert restored_id == original_id
    return {"original_image": original, "original_image_id": original_id, "new_image": expected, "new_image_id": image_id, "release_marker": marker, "rollback_verified": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", choices=["fallback", "outage", "crash", "backup", "image"])
    args = parser.parse_args()
    OUT.mkdir(mode=0o700, parents=True, exist_ok=True)
    assert pod_code("import os; print(os.environ['PROFILE_MODE'])") == "sample"
    assert pod_code("import json; from pathlib import Path; print(json.loads(Path('/lab-data/master_profile.json').read_text())['personal']['name'])") == "Alex Example"
    record = {"scenario": args.scenario, "started_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
    try:
        handlers = {"fallback": fault_test, "outage": lambda: fault_test(True), "crash": crash_test, "backup": backup_test, "image": image_test}
        record.update(result="PASS", evidence=handlers[args.scenario]())
    except Exception as error:
        record.update(result="FAIL", error=str(error)[:1800])
        raise
    finally:
        record["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        (OUT / (args.scenario + ".json")).write_text(json.dumps(record, indent=2))
        print("SCENARIO RESULT " + json.dumps(record), flush=True)


if __name__ == "__main__":
    main()
