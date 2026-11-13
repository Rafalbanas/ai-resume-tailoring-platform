"""The onboarding helper must not overwrite an owner's configuration or state."""

import json
import stat
from pathlib import Path

import pytest

from scripts.init_demo import initialize

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def checkout(tmp_path):
    (tmp_path / "data").mkdir()
    for name in (".env.example", "data/master_profile.example.json"):
        (tmp_path / name).write_bytes((ROOT / name).read_bytes())
    return tmp_path


def test_fictional_mock_setup_has_independent_secrets_and_no_cloud_fallback(checkout, capsys):
    initialize(checkout)
    settings = dict(line.split("=", 1) for line in (checkout / ".env").read_text().splitlines()
                    if line and not line.startswith("#"))
    assert settings["AI_PROVIDER"] == settings["LLM_PROVIDER"] == "mock"
    assert settings["LLM_FALLBACK_PROVIDER"] == "none"
    assert settings["PROFILE_MODE"] == "sample"
    assert settings["BASE_URL"] == "http://127.0.0.1:8000"
    assert not settings["GEMINI_API_KEY"]
    secrets = [settings[key] for key in ("APP_PASSWORD", "CSRF_SECRET", "PROCESSING_TOKEN", "BROWSER_PROCESSING_TOKEN")]
    assert len(set(secrets)) == 4 and all(len(value) >= 32 for value in secrets)
    output = capsys.readouterr().out
    assert all(value not in output for value in secrets)
    assert json.loads((checkout / "data/ai_settings.json").read_text()) == {"automatic_fallback": False}
    profile = json.loads((checkout / "data/master_profile.json").read_text())
    assert profile["personal"]["name"] == "Alex Example"
    skill = json.loads((checkout / "data/skills.json").read_text())["skills"][0]
    assert skill["name"] in profile["experience"][0]["facts"][0]
    for path in (checkout / ".env", checkout / "data/master_profile.json", checkout / "data/skills.json", checkout / "data/ai_settings.json"):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600


@pytest.mark.parametrize("name", [".env", "data/master_profile.json", "data/skills.json", "data/auth.json",
                                  "data/ai_settings.json", "data/sessions.sqlite3", "data/generated", "data/tasks",
                                  "data/resource_usage.sqlite3", "data/profile_photo", "data/reference_cvs"])
def test_existing_state_refused_without_any_writes(checkout, name):
    existing = checkout / name
    existing.write_text("private sentinel")
    before = {str(path.relative_to(checkout)): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    with pytest.raises(FileExistsError, match="nothing was changed"):
        initialize(checkout)
    after = {str(path.relative_to(checkout)): path.read_bytes() for path in checkout.rglob("*") if path.is_file()}
    assert before == after


def test_dangling_config_symlink_refused(checkout):
    (checkout / ".env").symlink_to(checkout / "missing")
    with pytest.raises(FileExistsError):
        initialize(checkout)
    assert not (checkout / "missing").exists()


def test_symlinked_data_directory_refused(checkout, tmp_path_factory):
    external = tmp_path_factory.mktemp("external-account")
    (external / "sentinel").write_text("untouched")
    for path in (checkout / "data").iterdir():
        path.unlink()
    (checkout / "data").rmdir()
    (checkout / "data").symlink_to(external, target_is_directory=True)
    with pytest.raises(FileExistsError):
        initialize(checkout)
    assert sorted(path.name for path in external.iterdir()) == ["sentinel"]
    assert not (checkout / ".env").exists()


def test_initialized_files_start_authenticated_mock_runtime(checkout):
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app

    initialize(checkout)
    settings = Settings(_env_file=checkout / ".env", data_dir=checkout / "data")
    app = create_app(settings)
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:
        assert client.get("/health").status_code == 200
        assert client.get("/", follow_redirects=False).status_code == 303
        assert app.state.profile.personal.name == "Alex Example"
        assert app.state.provider.resolve_chain() == ("mock", None)
        skill = app.state.skills_bank.get("skill_demo_python")
        assert app.state.skills_bank.eligible(skill)
        assert client.get("/login").status_code == 200
        response = client.post("/login", data={
            "username": settings.app_username, "password": settings.app_password,
            "csrf_token": client.cookies.get("csrf_token"),
        }, follow_redirects=False)
        assert response.status_code == 303
        assert client.get("/").status_code == 200
