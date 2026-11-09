"""Unit tests for scripts/sync_readme.py."""

from pathlib import Path

import pytest

from scripts.sync_readme import (
    generate_tech_stack_table,
    get_python_version,
    main,
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
    assert "| **Python** | [Dockerfile](Dockerfile) | Runtime |" in table
    assert "| **FastAPI** | [requirements.txt](requirements.txt) | Backend |" in table
    assert "| **Pydantic** | [requirements.txt](requirements.txt) | Core |" in table
    assert "| **pytest** | [requirements-dev.txt](requirements-dev.txt) | Testing |" in table
    assert '0.143.0' not in table


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
        "Python: <!-- PYTHON_VERSION:START -->0.0<!-- PYTHON_VERSION:END -->\n",
        encoding="utf-8",
    )

    # First run (should change)
    changed, summary = sync_readme(readme, repo_root, dry_run=False)
    assert changed is True
    assert "Python: 3.14" in summary

    updated_content = readme.read_text(encoding="utf-8")
    assert "<!-- PYTHON_VERSION:START -->3.14<!-- PYTHON_VERSION:END -->" in updated_content
    assert "| **FastAPI** | [requirements.txt](requirements.txt) |" in updated_content

    # Second run (should be idempotent, no changes)
    changed_again, _ = sync_readme(readme, repo_root, dry_run=False)
    assert changed_again is False

    # Dry-run check when clean
    changed_check, _ = sync_readme(readme, repo_root, dry_run=True)
    assert changed_check is False


@pytest.fixture
def documentation_repo(tmp_path):
    (tmp_path / 'requirements.txt').write_text('pydantic==2.14.2\npython-multipart==0.0.32\n')
    (tmp_path / 'requirements-dev.txt').write_text('-r requirements.txt\nruff==0.17.3\npytest-asyncio==1.4.1\n')
    (tmp_path / 'Dockerfile').write_text('FROM python:3.14-slim\n')
    readme = tmp_path / 'README.md'
    readme.write_text('Intro\n<!-- TECH_STACK:START --><!-- TECH_STACK:END -->\n'
                      'Python: <!-- PYTHON_VERSION:START -->0<!-- PYTHON_VERSION:END -->\nOutro\n')
    sync_readme(readme, tmp_path)
    return tmp_path, readme


@pytest.mark.parametrize('filename,old,new', [
    ('requirements.txt', 'pydantic==2.14.2', 'pydantic==2.14.3'),
    ('requirements.txt', 'python-multipart==0.0.32', 'python-multipart==0.0.33'),
    ('requirements-dev.txt', 'ruff==0.17.3', 'ruff==0.17.4'),
    ('requirements-dev.txt', 'pytest-asyncio==1.4.1', 'pytest-asyncio==1.4.1.post1'),
])
def test_dependabot_version_bumps_do_not_change_readme(documentation_repo, filename, old, new):
    root, readme = documentation_repo
    original = readme.read_bytes()
    requirements = root / filename
    requirements.write_text(requirements.read_text().replace(old, new))
    assert sync_readme(readme, root, dry_run=True)[0] is False
    assert sync_readme(readme, root)[0] is False
    assert readme.read_bytes() == original


@pytest.mark.parametrize('change', ['add', 'remove', 'runtime', 'source'])
def test_real_drift_detected_without_writing_and_generation_idempotent(documentation_repo, change):
    root, readme = documentation_repo
    original = readme.read_bytes()
    requirements = root / 'requirements.txt'
    if change == 'add':
        requirements.write_text(requirements.read_text() + 'fastapi==0.162.0\n')
    elif change == 'remove':
        requirements.write_text('python-multipart==0.0.32\n')
    elif change == 'source':
        requirements.write_text(requirements.read_text() + 'ruff==0.17.3\n')
    else:
        (root / 'Dockerfile').write_text('FROM python:3.15-slim\n')
    assert sync_readme(readme, root, dry_run=True)[0] is True
    assert readme.read_bytes() == original
    assert sync_readme(readme, root)[0] is True
    assert sync_readme(readme, root)[0] is False
    assert readme.read_text().startswith('Intro\n')
    assert readme.read_text().endswith('Outro\n')


def test_no_test_collection_or_environment_dependent_metrics(documentation_repo):
    root, readme = documentation_repo
    tests = root / 'tests'
    tests.mkdir()
    (tests / 'test_broken.py').write_text('this is intentionally invalid Python !!!')
    assert sync_readme(readme, root)[0] is False


def test_cli_check_exit_codes_and_read_only(documentation_repo, monkeypatch, capsys):
    root, readme = documentation_repo
    monkeypatch.setattr('sys.argv', ['sync_readme.py', '--check', '--repo-root', str(root)])
    assert main() == 0
    readme.write_text(readme.read_text().replace('**Pydantic**', '**Stale**'))
    original = readme.read_bytes()
    assert main() == 1
    assert readme.read_bytes() == original
    readme.unlink()
    assert main() == 2
    assert 'Error synchronizing README' in capsys.readouterr().err
