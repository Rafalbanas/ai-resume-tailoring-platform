"""Keep routine dependency updates isolated without disabling security fixes."""
from pathlib import Path

import yaml

BASE_DIR = Path(__file__).resolve().parents[1]
DEPENDABOT_PATH = BASE_DIR / ".github" / "dependabot.yml"


def test_dependabot_policy():
    config = yaml.safe_load(DEPENDABOT_PATH.read_text(encoding="utf-8"))
    assert config["version"] == 2
    updates = config["updates"]

    # 1. Active ecosystems/schedule
    # Check that 'pip', 'github-actions', and 'docker' exist and have correct schedules
    ecosystems = ["pip", "github-actions", "docker"]
    assert len(updates) == len(ecosystems)
    assert {block["package-ecosystem"] for block in updates} == set(ecosystems)
    expected_schedule = {
        "interval": "weekly",
        "day": "monday",
        "time": "08:00",
        "timezone": "Europe/Warsaw",
    }
    expected_limit = 5

    for eco in ecosystems:
        block = next(u for u in updates if u.get("package-ecosystem") == eco)
        assert block.get("schedule") == expected_schedule
        assert block.get("open-pull-requests-limit") == expected_limit

    # 2. Pip cooldown
    pip_block = next(u for u in updates if u.get("package-ecosystem") == "pip")
    assert pip_block.get("cooldown", {}).get("default-days") == 7
    assert "ignore" not in pip_block
    assert "target-branch" not in pip_block

    # 3. Group separation
    pip_groups = pip_block.get("groups", {})

    # Runner patterns
    runner_group = pip_groups.get("python-test-runner", {})
    assert set(runner_group.get("patterns", [])) == {"pytest", "pytest-asyncio"}

    # Browser patterns
    browser_group = pip_groups.get("python-browser", {})
    assert set(browser_group.get("patterns", [])) == {"playwright"}
    assert set(browser_group.get("update-types", [])) == {"minor", "patch"}

    # General group patterns
    patch_group = pip_groups.get("python-minor-and-patch", {})
    assert set(patch_group.get("patterns", [])) == {"*"}
    assert set(patch_group.get("update-types", [])) == {"minor", "patch"}
    assert set(patch_group.get("exclude-patterns", [])) == {"playwright", "pytest", "pytest-asyncio"}

    # 4. Docker ignore
    docker_block = next(u for u in updates if u.get("package-ecosystem") == "docker")
    docker_ignore = docker_block.get("ignore", [])
    python_ignore = next(i for i in docker_ignore if i.get("dependency-name") == "python")
    update_types = python_ignore.get("update-types", [])
    assert "version-update:semver-major" in update_types
    assert "version-update:semver-minor" in update_types
