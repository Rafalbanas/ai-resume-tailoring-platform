"""Render before changing a saved CV; retain prior versions and roll back errors."""
import os
import shutil
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4


@contextmanager
def staged_artifacts(folder: Path):
    with tempfile.TemporaryDirectory(prefix='.export-', dir=folder) as path:
        yield Path(path)


def commit_artifacts(folder: Path, staged: Path, save_json) -> None:
    files = ('resume.json', 'metadata.json', 'resume.pdf', 'resume.docx')
    version = folder / 'versions' / (datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '-' + uuid4().hex[:8])
    version.mkdir(parents=True)
    existing = []
    for name in files:
        if (folder / name).is_file():
            shutil.copy2(folder / name, version / name)
            existing.append(name)
    try:
        for name in ('resume.pdf', 'resume.docx'):
            os.replace(staged / name, folder / name)
        save_json()
    except Exception:
        for name in files:
            if name in existing:
                shutil.copy2(version / name, folder / name)
            else:
                (folder / name).unlink(missing_ok=True)
        raise
