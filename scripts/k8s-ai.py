"""Connect the kind lab to host-loopback Ollama and Gemini; never print credentials."""

import argparse
import base64
import ipaddress
import json
import os
import subprocess
from pathlib import Path

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
KUBE = os.environ.get("CVTAILOR_LAB_KUBECONFIG", str(Path.home() / ".kube/cvtailor-lab.config"))
CLI = ["kubectl", "--kubeconfig", KUBE, "--context", "kind-cvtailor-lab", "-n", "cvtailor-lab"]
BRIDGE = "cvtailor-lab-ollama-bridge"
LABEL = "com.cvtailor.lab.ollama-bridge"


def call(args, payload=None, quiet=False):
    result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=210)
    if result.returncode:
        # Payloads can contain a Secret. Keep command diagnostics out of exceptions.
        raise RuntimeError(f"Command failed: {args[0]} {args[1]} (exit {result.returncode})")
    if not quiet and result.stdout.strip():
        print(result.stdout.strip(), flush=True)
    return result.stdout


def k(*args, payload=None, quiet=False):
    return call(CLI + list(args), payload=payload, quiet=quiet)


def patch(kind, name, data):
    k("patch", kind, name, "--type=merge", "--patch-file=/dev/stdin", payload=json.dumps(data))


def restart():
    k("rollout", "restart", "deployment/cvtailor")
    k("rollout", "status", "deployment/cvtailor", "--timeout=180s")


def verify():
    code = """import asyncio, json, urllib.request
from app.core.config import Settings
from app.services.ollama_provider import OllamaProvider
from app.services.gemini_provider import GeminiProvider
async def check():
    settings = Settings()
    for provider in (OllamaProvider(settings), GeminiProvider(settings)):
        result = await provider.health()
        assert result.get('status') == 'ok', provider.name
        print(json.dumps(result))
    assert urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=5).status == 200
asyncio.run(check())
"""
    k("exec", "deployment/cvtailor", "-c", "app", "--", "python", "-c", code)


def bridge_details():
    result = subprocess.run(["docker", "inspect", BRIDGE], text=True, capture_output=True, timeout=15)
    if result.returncode:
        return None
    info = json.loads(result.stdout)[0]
    if info["Config"]["Labels"].get(LABEL) != "true":
        raise RuntimeError("Bridge container name is already used by another owner")
    return info


def prepare_bridge():
    network = json.loads(call(["docker", "network", "inspect", "kind"], quiet=True))[0]
    gateway = next(c["Gateway"] for c in network["IPAM"]["Config"] if c.get("Gateway") and ipaddress.ip_address(c["Gateway"]).version == 4)
    node = json.loads(call(["docker", "inspect", "cvtailor-lab-control-plane"], quiet=True))[0]
    node_ip = node["NetworkSettings"]["Networks"]["kind"]["IPAddress"]
    ipaddress.ip_address(node_ip)
    image = call(["docker", "image", "inspect", "nginx:1.27-alpine", "--format", "{{.Id}}"], quiet=True).strip()
    runtime = ROOT / ".k8s-lab"
    runtime.mkdir(mode=0o700, exist_ok=True)
    config = runtime / "ollama-bridge.conf"
    text = f"""pid /tmp/nginx.pid;
error_log /dev/stderr warn;
events {{ worker_connections 64; }}
http {{
  access_log off;
  server {{
    listen {gateway}:11435;
    allow {node_ip};
    deny all;
    client_max_body_size 16m;
    location /api/ {{
      proxy_pass http://127.0.0.1:11434;
      proxy_http_version 1.1;
      proxy_set_header Connection "";
      proxy_buffering off;
      proxy_read_timeout 600s;
      proxy_send_timeout 600s;
    }}
    location / {{ return 404; }}
  }}
}}
"""
    existing = bridge_details()
    if existing:
        if not config.is_file() or config.read_text() != text:
            raise RuntimeError("Bridge network changed; remove the owned bridge container before reconnecting")
        call(["docker", "start", BRIDGE], quiet=True)
    else:
        config.write_text(text)
        call(["docker", "run", "-d", "--name", BRIDGE, "--label", LABEL + "=true",
              "--restart", "unless-stopped", "--network", "host", "--user", "101:101",
              "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges:true",
              "--memory", "64m", "--cpus", "0.25", "--tmpfs", "/tmp:rw,nosuid,noexec,size=8m",
              "--tmpfs", "/var/cache/nginx:rw,nosuid,noexec,size=8m,uid=101,gid=101",
              "--mount", f"type=bind,src={config},dst=/etc/nginx/nginx.conf,readonly",
              "--entrypoint", "nginx", image, "-g", "daemon off;"], quiet=True)
    firewall = call(["ufw", "status"], quiet=True)
    managed = "Status: active" in firewall
    if managed:
        call(["ufw", "allow", "from", node_ip, "to", gateway, "port", "11435", "proto", "tcp",
              "comment", "cvtailor-lab-ollama"], quiet=True)
    (runtime / "bridge-network.json").write_text(json.dumps({"gateway": gateway, "node_ip": node_ip, "firewall_managed": managed}))
    print(f"Ollama bridge: {gateway}:11435; allowed source: {node_ip}", flush=True)
    return f"http://{gateway}:11435"


def enable():
    values = dotenv_values(ROOT / ".env")
    key = os.environ.get("GEMINI_API_KEY") or values.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY is missing; set it in the host .env or environment")
    settings = json.loads((ROOT / "deploy/k8s/ai/provider-config.json").read_text())
    for name in ("OLLAMA_MODEL", "GEMINI_MODEL"):
        settings[name] = os.environ.get(name) or values.get(name) or settings[name]
    old_config = json.loads(k("get", "configmap", "cvtailor-config", "-o", "json", quiet=True))["data"]
    old_secret = json.loads(k("get", "secret", "cvtailor-secrets", "-o", "json", quiet=True))["data"].get("GEMINI_API_KEY")
    settings["OLLAMA_BASE_URL"] = prepare_bridge()
    try:
        patch("secret", "cvtailor-secrets", {"data": {"GEMINI_API_KEY": base64.b64encode(key.encode()).decode()}})
        patch("configmap", "cvtailor-config", {"data": settings})
        restart()
        verify()
    except Exception:
        patch("configmap", "cvtailor-config", {"data": {**{name: None for name in settings}, **old_config}})
        patch("secret", "cvtailor-secrets", {"data": {"GEMINI_API_KEY": old_secret}})
        restart()
        raise
    print("Connected: Ollama primary, Gemini fallback. Sample profile retained. API key stored in Secret.")


def mock():
    settings = json.loads((ROOT / "deploy/k8s/ai/provider-config.json").read_text())
    patch("configmap", "cvtailor-config", {"data": {**{name: None for name in settings}, "OLLAMA_BASE_URL": None,
          "AI_PROVIDER": "mock", "LLM_PROVIDER": "mock", "LLM_FALLBACK_PROVIDER": "none"}})
    patch("secret", "cvtailor-secrets", {"data": {"GEMINI_API_KEY": None}})
    restart()
    if bridge_details():
        call(["docker", "stop", BRIDGE], quiet=True)
    network_path = ROOT / ".k8s-lab/bridge-network.json"
    if network_path.is_file():
        network = json.loads(network_path.read_text())
        if network.get("firewall_managed"):
            call(["ufw", "--force", "delete", "allow", "from", network["node_ip"], "to", network["gateway"],
                  "port", "11435", "proto", "tcp"], quiet=True)
            network["firewall_managed"] = False
            network_path.write_text(json.dumps(network))
    print("Mock mode restored; Gemini key removed from the lab Secret; bridge stopped; lab firewall rule removed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=["enable", "mock"])
    args = parser.parse_args()
    {"enable": enable, "mock": mock}[args.mode]()
