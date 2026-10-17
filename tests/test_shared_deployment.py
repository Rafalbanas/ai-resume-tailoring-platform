"""A shared image rollout must wait for both accounts' background work."""
import importlib.util
import json
import os
from pathlib import Path

import pytest


def test_deployment_drain_waits_for_demo_jobs_and_releases_lock(tmp_path, monkeypatch):
    path = Path(__file__).resolve().parents[1] / 'deploy/k8s/production/deploy.py'
    spec = importlib.util.spec_from_file_location('shared_deploy_check', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    private, demo = tmp_path / 'main', tmp_path / 'demo'
    for directory in (private, demo):
        (directory / 'tasks').mkdir(parents=True)
    task = demo / 'tasks/demo-only.json'
    task.write_text(json.dumps({'status': 'queued'}))
    monkeypatch.setattr(module, 'DATA', private)
    # The production entrypoint is root-owned; CI tests should not require root.
    monkeypatch.setattr(module.os, 'fchown', lambda *args: None)
    with pytest.raises(TimeoutError, match='Active analyses'):
        module.drain(timeout=0)
    task.write_text(json.dumps({'status': 'completed'}))
    descriptor = module.drain(timeout=0)
    os.close(descriptor)
