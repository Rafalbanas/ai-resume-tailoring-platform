import json

from app.core.config import Settings


def test_default(monkeypatch):
    """
    Verify that the default model is gemma4:12b-it-q4_K_M
    when OLLAMA_MODEL is not provided in the environment.
    """
    monkeypatch.delenv("OLLAMA_MODEL", raising=False)
    # We use _env_file=None to ensure it doesn't load the local .env
    settings = Settings(_env_file=None)
    assert settings.ollama_model == "gemma4:12b-it-q4_K_M"


def test_override(monkeypatch):
    """
    Verify that the model can be overridden via the OLLAMA_MODEL environment variable.
    """
    monkeypatch.setenv("OLLAMA_MODEL", "qwen3.5:9b")
    settings = Settings(_env_file=None)
    assert settings.ollama_model == "qwen3.5:9b"


def test_config_consistency():
    """
    Verify that the OLLAMA_MODEL matches across all configuration files.
    """
    expected = "gemma4:12b-it-q4_K_M"

    # 1. provider-config.json
    with open("deploy/k8s/ai/provider-config.json", "r") as f:
        data = json.load(f)
        assert data["OLLAMA_MODEL"] == expected

    # 2. .env.example
    with open(".env.example", "r") as f:
        lines = f.readlines()
        # Find the line starting with OLLAMA_MODEL=
        ollama_model_line = next(line for line in lines if line.startswith("OLLAMA_MODEL="))
        assert ollama_model_line.strip().split("=")[1] == expected

    # 3. production/resources.json (ConfigMaps)
    with open("deploy/k8s/production/resources.json", "r") as f:
        data = json.load(f)
        models = {
            item["metadata"]["name"]: item["data"]["OLLAMA_MODEL"]
            for item in data["items"]
            if item["kind"] == "ConfigMap" and "OLLAMA_MODEL" in item.get("data", {})
        }
        assert models == {"cvtailor-config": expected, "cvtailor-demo-config": expected}
