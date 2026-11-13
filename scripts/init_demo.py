"""Initialize a fresh checkout with fictional data and mock AI; never overwrite state.

Uses only Python's standard library. Run from the repository root:
    python3 scripts/init_demo.py
"""

import json
import secrets
from pathlib import Path


def initialize(root: Path) -> None:
    data = root / "data"
    # Refuse even an existing empty file or dangling symlink. This helper is for
    # new checkouts, never for converting an owner's installation into a demo.
    allowed = {"master_profile.example.json", "skills.example.json"}
    if (root / ".env").exists() or (root / ".env").is_symlink() or data.is_symlink() or any(
        path.name not in allowed for path in data.iterdir()
    ):
        raise FileExistsError("Existing configuration or account state found. Use a fresh checkout; nothing was changed.")

    settings = {
        "APP_USERNAME": "local-demo",
        "APP_PASSWORD": secrets.token_urlsafe(24),
        "CSRF_SECRET": secrets.token_hex(32),
        "PROCESSING_TOKEN": secrets.token_hex(32),
        "BROWSER_PROCESSING_TOKEN": secrets.token_hex(32),
        "BASE_URL": "http://127.0.0.1:8000",
        "AI_PROVIDER": "mock",
        "LLM_PROVIDER": "mock",
        "LLM_FALLBACK_PROVIDER": "none",
        "PROFILE_MODE": "sample",
    }
    example = (root / ".env.example").read_text(encoding="utf-8")
    env = "\n".join(
        f"{line.split('=', 1)[0]}={settings[line.split('=', 1)[0]]}"
        if "=" in line and line.split("=", 1)[0] in settings else line
        for line in example.splitlines()
    ) + "\n"
    profile = (data / "master_profile.example.json").read_text(encoding="utf-8")
    skills = {
        "version": 1,
        "skills": [{
            "id": "skill_demo_python", "name": "Python", "category": "Programming",
            "level": "hands_on", "verified": True, "enabled": True,
            "allowed_in_cv": True, "priority": 7,
            "evidence": [{"source_type": "employment", "source_id": "experience:0:fact:0",
                          "description": "Fictional Python support automation in the bundled example profile."}],
            "notes": "Synthetic demo only; not a real candidate qualification.",
        }],
    }
    outputs = {
        root / ".env": env,
        data / "master_profile.json": profile,
        data / "skills.json": json.dumps(skills, indent=2) + "\n",
        data / "ai_settings.json": '{"automatic_fallback": false}\n',
    }
    for path, content in outputs.items():
        # Exclusive creation also protects against overwrites after preflight.
        with path.open("x", encoding="utf-8") as handle:
            path.chmod(0o600)
            handle.write(content)
    print("Fictional local demo initialized. Read APP_USERNAME and APP_PASSWORD in .env privately.")
    print("Next: docker compose up -d --build")


if __name__ == "__main__":
    try:
        initialize(Path(__file__).resolve().parents[1])
    except FileExistsError as error:
        raise SystemExit(str(error)) from None
