#!/usr/bin/env python3
"""Reject runtime/dependency drift before trusting local test results."""
import argparse
import importlib.metadata
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check(*, dev=False, python_version=None, package_version=importlib.metadata.version):
    errors = []
    expected = re.search(r'FROM python:(\d+\.\d+)', (ROOT / 'Dockerfile').read_text())[1]
    actual = python_version or '.'.join(map(str, sys.version_info[:2]))
    if actual != expected:
        errors.append(f'Python: expected {expected}, found {actual}. Use the project Docker image or matching Python.')
    files = ['requirements.txt'] + (['requirements-dev.txt'] if dev else [])
    for filename in files:
        for line in (ROOT / filename).read_text().splitlines():
            match = re.fullmatch(r'([\w-]+)(?:\[[\w, -]+\])?==([^\s]+)', line.strip())
            if not match:
                continue
            name, pinned = match.groups()
            try:
                found = package_version(name)
            except importlib.metadata.PackageNotFoundError:
                found = '<missing>'
            if found != pinned:
                errors.append(f'{name}: expected {pinned}, found {found}')
    return errors


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dev', action='store_true', help='Also check development dependencies')
    args = parser.parse_args()
    problems = check(dev=args.dev)
    for problem in problems:
        print(problem)
    if not problems:
        print('Environment matches the Docker runtime and pinned dependencies.')
    raise SystemExit(bool(problems))
