"""Unit tests for scripts/sync_readme.py."""

from pathlib import Path

from scripts.sync_readme import (
    generate_tech_stack_table,
    get_python_version,
    parse_requirements,
    replace_marker,
    sync_readme,
)


def test_parse_requirements(tmp_path: Path):
    req_file = tmp_path / "requirements.txt"
    req_file.write_text(
        "# Comment\n"
        "-r other.txt\n"
        "fastapi==0.143.0\n"
        "uvicorn[standard]==0.54.0\n"
        "Pillow==12.3.0\n",
        encoding="utf-8",
    )

    reqs = parse_requirements(req_file)
    assert reqs == {
        "fastapi": "0.143.0",
        "uvicorn": "0.54.0",
        "pillow": "12.3.0",
    }


def test_replace_marker_multiline():
    content = "Intro\n<!-- TECH_STACK:START -->\nold table\n<!-- TECH_STACK:END -->\nOutro"
    new_content = replace_marker(content, "TECH_STACK", "new table", inline=False)
    assert new_content == "Intro\n<!-- TECH_STACK:START -->\nnew table\n<!-- TECH_STACK:END -->\nOutro"


def test_replace_marker_inline():
    content = "Total tests: (<!-- TEST_COUNT:START -->100<!-- TEST_COUNT:END --> tests)"
    new_content = replace_marker(content, "TEST_COUNT", "603", inline=True)
    assert new_content == "Total tests: (<!-- TEST_COUNT:START -->603<!-- TEST_COUNT:END --> tests)"


def test_replace_marker_no_match():
    content = "No markers here"
    new_content = replace_marker(content, "TEST_COUNT", "603", inline=True)
    assert new_content == content


def test_get_python_version_from_dockerfile(tmp_path: Path):
    dockerfile = tmp_path / "Dockerfile"
    dockerfile.write_text("FROM python:3.14-slim\nWORKDIR /app\n", encoding="utf-8")
    assert get_python_version(tmp_path) == "3.14"


def test_generate_tech_stack_table():
    prod = {"fastapi": "0.143.0", "pydantic": "2.14.1"}
    dev = {"pytest": "9.1.1"}
    table = generate_tech_stack_table(prod, dev, "3.14")
    assert "| **Python** | `3.14` | Runtime |" in table
    assert "| **FastAPI** | `0.143.0` | Backend |" in table
    assert "| **Pydantic** | `2.14.1` | Core |" in table
    assert "| **pytest** | `9.1.1` | Testing |" in table


def test_sync_readme_end_to_end(tmp_path: Path):
    # Setup dummy repository structure
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    (repo_root / "Dockerfile").write_text("FROM python:3.14-slim\n", encoding="utf-8")
    (repo_root / "requirements.txt").write_text("fastapi==0.143.0\n", encoding="utf-8")
    (repo_root / "requirements-dev.txt").write_text("pytest==9.1.1\n", encoding="utf-8")

    tests_dir = repo_root / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_example.py").write_text("def test_one(): pass\ndef test_two(): pass\n", encoding="utf-8")

    readme = repo_root / "README.md"
    readme.write_text(
        "# Title\n\n"
        "<!-- TECH_STACK:START -->\n<!-- TECH_STACK:END -->\n\n"
        "Tests: <!-- TEST_COUNT:START -->0<!-- TEST_COUNT:END -->\n"
        "Python: <!-- PYTHON_VERSION:START -->0.0<!-- PYTHON_VERSION:END -->\n",
        encoding="utf-8",
    )

    # First run (should change)
    changed, summary = sync_readme(readme, repo_root, dry_run=False)
    assert changed is True
    assert "Python: 3.14" in summary

    updated_content = readme.read_text(encoding="utf-8")
    assert "<!-- TEST_COUNT:START -->2<!-- TEST_COUNT:END -->" in updated_content
    assert "<!-- PYTHON_VERSION:START -->3.14<!-- PYTHON_VERSION:END -->" in updated_content
    assert "| **FastAPI** | `0.143.0` |" in updated_content

    # Second run (should be idempotent, no changes)
    changed_again, _ = sync_readme(readme, repo_root, dry_run=False)
    assert changed_again is False

    # Dry-run check when clean
    changed_check, _ = sync_readme(readme, repo_root, dry_run=True)
    assert changed_check is False
