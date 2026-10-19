#!/usr/bin/env python3
"""Select role dependencies from the single, Dependabot-managed pin file."""
import argparse
import re
from pathlib import Path

DOCUMENTS = {'weasyprint', 'python-docx', 'pypdf', 'pillow', 'pillow-heif', 'pypdfium2'}
BROWSER = {'playwright'}


def requirements(role, path=None):
    path = path or Path(__file__).resolve().parents[1] / 'requirements.txt'
    lines = path.read_text().splitlines()
    selected = []
    for line in lines:
        match = re.fullmatch(r'([\w-]+)(?:\[[\w, -]+\])?==[^\s]+', line.strip())
        if not match:
            if line.strip() and not line.lstrip().startswith('#'):
                raise ValueError('Runtime dependencies must use exact pins')
            continue
        name = match[1].lower()
        if role == 'full' or name not in DOCUMENTS | BROWSER or role == 'documents' and name in DOCUMENTS or role == 'browser' and name in BROWSER:
            selected.append(line)
    return selected


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=['api', 'documents', 'browser', 'full'])
    print('\n'.join(requirements(parser.parse_args().role)))
