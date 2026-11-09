"""Guard read-only documentation checks, including Dependabot version bumps."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_readme_workflow_does_not_mutate_main_or_install_test_dependencies():
    workflow = (ROOT / '.github/workflows/sync-readme.yml').read_text(encoding='utf-8')
    assert 'contents: read' in workflow
    assert 'contents: write' not in workflow
    assert 'python scripts/sync_readme.py --check' in workflow
    for command in ('git push', 'git commit', 'pip install', '[skip ci]'):
        assert command not in workflow


def test_ci_checks_documentation_before_expensive_regressions():
    workflow = (ROOT / '.github/workflows/ci.yml').read_text(encoding='utf-8')
    assert workflow.index('python scripts/sync_readme.py --check') < workflow.index('run: pytest -q')


def test_readme_does_not_claim_a_fixed_test_count():
    readme = (ROOT / 'README.md').read_text(encoding='utf-8')
    assert 'TEST_COUNT:START' not in readme
    assert 'suite (767 tests)' not in readme
    assert 'pytest --collect-only -q' in readme
