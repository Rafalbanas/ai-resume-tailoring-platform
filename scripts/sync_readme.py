#!/usr/bin/env python3
"""Synchronize pinned dependency versions, runtime, and test counts in README.md.

This script parses requirements.txt, requirements-dev.txt, Dockerfile, and runs
pytest to extract exact versions and test suite statistics. It then replaces
the content within marked comments in README.md.

Markers supported:
- <!-- TECH_STACK:START --> ... <!-- TECH_STACK:END -->
- <!-- TEST_COUNT:START --> ... <!-- TEST_COUNT:END -->
- <!-- PYTHON_VERSION:START --> ... <!-- PYTHON_VERSION:END -->
"""

import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

# Metadata catalog for known project dependencies: (Display Name, Category, Purpose)
PACKAGE_CATALOG: dict[str, tuple[str, str, str]] = {
    "fastapi": ("FastAPI", "Backend", "Asynchronous REST API framework & routing"),
    "uvicorn": ("Uvicorn", "Backend", "High-performance ASGI production server"),
    "pydantic": ("Pydantic", "Core", "Data validation, settings, and domain schemas"),
    "pydantic-settings": ("Pydantic Settings", "Core", "Settings management and environment parsing"),
    "weasyprint": ("WeasyPrint", "Document Engine", "Visual CSS / Paged Media PDF generation"),
    "pypdfium2": ("PyPDFium2", "Document Engine", "PDF geometry, text layout & bounding box inspection"),
    "pypdf": ("pypdf", "Document Engine", "PDF manipulation, stream extraction & structural checks"),
    "python-docx": ("python-docx", "Document Engine", "ATS-friendly Microsoft Word document generation"),
    "playwright": ("Playwright", "Job Extraction", "Headless Chromium browser automation & SSR fallback"),
    "beautifulsoup4": ("BeautifulSoup4", "Job Extraction", "Resilient HTML parsing & job posting sanitization"),
    "httpx": ("HTTPX", "Networking", "Async HTTP client for MCP, Gemini, and external APIs"),
    "jinja2": ("Jinja2", "Templates", "Jinja2 HTML resume template rendering engine"),
    "pillow": ("Pillow", "Media", "Profile photo validation, scaling, and cropping"),
    "pillow-heif": ("pillow-heif", "Media", "HEIF / HEIC photo decoding for mobile camera uploads"),
    "argon2-cffi": ("Argon2-cffi", "Security", "Argon2id password hashing & credential storage"),
    "itsdangerous": ("itsdangerous", "Security", "Cryptographic signing & HMAC summary review attestation"),
    "email-validator": ("email-validator", "Validation", "RFC-compliant email address validation"),
    "python-multipart": ("python-multipart", "Backend", "Multipart form data & resume file upload streaming"),
    "pytest": ("pytest", "Testing", "Automated test runner and assertion framework"),
    "pytest-asyncio": ("pytest-asyncio", "Testing", "Asynchronous test execution for pytest"),
    "ruff": ("Ruff", "Tooling", "Fast Python linter and code style enforcement"),
}


def get_repo_root() -> Path:
    """Find repository root relative to this script."""
    return Path(__file__).resolve().parent.parent


def get_python_version(repo_root: Path) -> str:
    """Extract target Python version from Dockerfile or CI workflow."""
    dockerfile = repo_root / "Dockerfile"
    if dockerfile.is_file():
        match = re.search(r"FROM\s+python:([0-9]+\.[0-9]+)", dockerfile.read_text(encoding="utf-8"))
        if match:
            return match.group(1)

    ci_file = repo_root / ".github" / "workflows" / "ci.yml"
    if ci_file.is_file():
        match = re.search(r'python-version:\s*"?([0-9]+\.[0-9]+)"?', ci_file.read_text(encoding="utf-8"))
        if match:
            return match.group(1)

    return "3.14"


def parse_requirements(file_path: Path) -> dict[str, str]:
    """Parse requirement file into a dict of {canonical_name: version}."""
    if not file_path.is_file():
        return {}

    reqs: dict[str, str] = {}
    pattern = re.compile(r"^\s*([a-zA-Z0-9_\-\[\]]+)\s*==\s*([a-zA-Z0-9_\.\-]+)")

    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-r"):
            continue
        match = pattern.match(line)
        if match:
            raw_pkg, version = match.group(1), match.group(2)
            base_pkg = re.sub(r"\[.*\]", "", raw_pkg).lower().strip()
            reqs[base_pkg] = version

    return reqs


def count_tests_ast(repo_root: Path) -> int:
    """Fallback: count test functions in tests/ directory using AST parsing."""
    tests_dir = repo_root / "tests"
    if not tests_dir.is_dir():
        return 0

    total = 0
    for py_file in tests_dir.glob("test_*.py"):
        try:
            tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        except Exception:
            continue

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith("test_"):
                total += 1
            elif isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
                for sub_node in node.body:
                    if isinstance(sub_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and sub_node.name.startswith("test_"):
                        total += 1

    return total


def get_test_count(repo_root: Path) -> int:
    """Discover the exact number of tests via pytest --collect-only, falling back to AST."""
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q"],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=30,
        )
        combined = proc.stdout + "\n" + proc.stderr
        match = re.search(r"(\d+)\s+tests?\s+collected", combined)
        if match:
            return int(match.group(1))

        # Check line count in -q output if line-based
        test_lines = [
            line for line in proc.stdout.splitlines()
            if "::" in line and not line.startswith("=") and not line.startswith("<")
        ]
        if test_lines:
            return len(test_lines)
    except Exception:
        pass

    ast_count = count_tests_ast(repo_root)
    return ast_count


def generate_tech_stack_table(
    prod_reqs: dict[str, str],
    dev_reqs: dict[str, str],
    python_version: str,
) -> str:
    """Generate Markdown table of technologies, pinned versions, categories, and purposes."""
    lines = [
        "| Component | Pinned Version | Category | Purpose |",
        "|---|---|---|---|",
        f"| **Python** | `{python_version}` | Runtime | Container runtime & execution environment |",
    ]

    all_pkgs: dict[str, str] = {**prod_reqs, **dev_reqs}

    def sort_key(item: tuple[str, str]) -> tuple[int, str]:
        pkg = item[0]
        meta = PACKAGE_CATALOG.get(pkg)
        if not meta:
            return (99, pkg)
        category_order = {
            "Backend": 1,
            "Core": 2,
            "Document Engine": 3,
            "Job Extraction": 4,
            "Networking": 5,
            "Templates": 6,
            "Media": 7,
            "Security": 8,
            "Validation": 9,
            "Testing": 10,
            "Tooling": 11,
        }
        return (category_order.get(meta[1], 50), meta[0])

    for pkg, version in sorted(all_pkgs.items(), key=sort_key):
        meta = PACKAGE_CATALOG.get(pkg)
        if meta:
            name, category, purpose = meta
        else:
            name, category, purpose = pkg.capitalize(), "Dependency", "Application dependency"
        lines.append(f"| **{name}** | `{version}` | {category} | {purpose} |")

    return "\n".join(lines)


def replace_marker(content: str, marker_name: str, replacement: str, inline: bool = False) -> str:
    """Replace content between <!-- MARKER:START --> and <!-- MARKER:END -->."""
    pattern = re.compile(
        rf"(<!--\s*{re.escape(marker_name)}:START\s*-->).*?(<!--\s*{re.escape(marker_name)}:END\s*-->)",
        re.DOTALL,
    )
    if not pattern.search(content):
        return content

    def repl_func(match: re.Match[str]) -> str:
        prefix = match.group(1)
        suffix = match.group(2)
        if inline:
            return f"{prefix}{replacement}{suffix}"
        return f"{prefix}\n{replacement}\n{suffix}"

    return pattern.sub(repl_func, content)


def sync_readme(
    readme_path: Path,
    repo_root: Path,
    dry_run: bool = False,
) -> tuple[bool, str]:
    """Synchronize README markers with current repo files."""
    if not readme_path.is_file():
        raise FileNotFoundError(f"README not found at {readme_path}")

    original_content = readme_path.read_text(encoding="utf-8")
    content = original_content

    python_version = get_python_version(repo_root)
    prod_reqs = parse_requirements(repo_root / "requirements.txt")
    dev_reqs = parse_requirements(repo_root / "requirements-dev.txt")
    test_count = get_test_count(repo_root)

    # 1. Update TECH_STACK table
    table = generate_tech_stack_table(prod_reqs, dev_reqs, python_version)
    content = replace_marker(content, "TECH_STACK", table, inline=False)

    # 2. Update TEST_COUNT markers
    content = replace_marker(content, "TEST_COUNT", str(test_count), inline=True)

    # 3. Update PYTHON_VERSION markers
    content = replace_marker(content, "PYTHON_VERSION", python_version, inline=True)

    changed = content != original_content
    summary = (
        f"Python: {python_version}, Tests: {test_count}, "
        f"Prod Packages: {len(prod_reqs)}, Dev Packages: {len(dev_reqs)}"
    )

    if changed and not dry_run:
        readme_path.write_text(content, encoding="utf-8")

    return changed, summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Synchronize README.md dependency versions and test counts.")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if README.md is up to date without writing. Exits with 1 if out of date.",
    )
    parser.add_argument(
        "--readme",
        type=Path,
        default=None,
        help="Path to README.md file (default: <repo_root>/README.md)",
    )
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=None,
        help="Path to repository root (default: script parent directory)",
    )

    args = parser.parse_args()
    repo_root = args.repo_root or get_repo_root()
    readme_path = args.readme or (repo_root / "README.md")

    try:
        changed, summary = sync_readme(readme_path, repo_root, dry_run=args.check)
    except Exception as exc:
        print(f"Error synchronizing README: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if changed:
            print(f"README.md is OUT OF DATE ({summary}). Run 'python scripts/sync_readme.py' to update.")
            return 1
        print(f"README.md is up to date ({summary}).")
        return 0

    if changed:
        print(f"Successfully updated README.md ({summary}).")
    else:
        print(f"README.md is already up to date ({summary}).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
