"""The Playwright installer cannot bootstrap the native dependencies of its own driver."""
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("stage", ["browser-deps", "full-deps"])
def test_node_native_dependency_is_installed_before_playwright_starts(stage):
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    # Join Dockerfile continuations, then isolate the stage instead of accepting
    # a package installed in an unrelated image (the cause of PR #120).
    dockerfile = dockerfile.replace("\\\n", " ")
    stages = re.split(r"(?m)^FROM ", dockerfile)
    source = next(part for part in stages if part.splitlines()[0].endswith(f" AS {stage}"))
    install = re.search(r"apt-get install [^\n&;]*\blibatomic1\b", source)
    assert install, f"{stage} must bootstrap the Playwright Node driver with libatomic1"
    assert source.index("apt-get update") < install.start()
    assert install.end() < source.index("python -m playwright install")
