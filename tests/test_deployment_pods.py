"""Terminal Kubernetes pod records must not break release or rollback checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def deployer():
    path = Path(__file__).resolve().parents[1] / 'deploy/k8s/production/deploy.py'
    spec = importlib.util.spec_from_file_location('pod_deployer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def pod(name, phase='Running', ready=True, deleting=False, image='approved-image'):
    metadata = {'name': name}
    if deleting:
        metadata['deletionTimestamp'] = '2026-10-29T00:00:00Z'
    return {'metadata': metadata, 'status': {
        'phase': phase, 'conditions': [{'type': 'Ready', 'status': 'True' if ready else 'False'}],
        'containerStatuses': [{'name': 'app', 'ready': ready, 'imageID': image}],
    }}


def test_terminal_pods_are_ignored_even_with_stale_ready_conditions(deployer):
    live = pod('live')
    assert deployer.ready_production_pod([
        pod('evicted', phase='Failed'), pod('completed', phase='Succeeded'),
        pod('deleting', deleting=True), live,
    ]) is live


@pytest.mark.parametrize('pods', [
    [], [pod('failed', phase='Failed')], [pod('completed', phase='Succeeded')],
    [pod('unknown', phase='Unknown')], [pod('pending', phase='Pending')],
    [pod('unready', ready=False)], [pod('deleting', deleting=True)],
    [pod('one'), pod('two')], [pod('live'), pod('pending', phase='Pending')],
    [pod('live'), pod('unknown', phase='Unknown')], [pod('live'), pod('unready', ready=False)],
])
def test_missing_ambiguous_or_unready_live_pods_still_block_deployment(deployer, pods):
    with pytest.raises(AssertionError):
        deployer.ready_production_pod(pods)


def mock_health(monkeypatch, deployer):
    response = MagicMock()
    response.__enter__.return_value.status = 200
    monkeypatch.setattr(deployer.urllib.request, 'urlopen', lambda *args, **kwargs: response)


@pytest.mark.parametrize('bad_image', [False, True])
def test_already_deployed_image_check_ignores_evicted_pod_but_checks_digest(deployer, monkeypatch, bad_image):
    revision, digest = 'b' * 40, 'sha256:' + 'b' * 64
    image = deployer.REPOSITORY + '@' + digest
    deployment = {'metadata': {'annotations': {'cvtailor.dev/revision': revision}},
                  'spec': {'template': {'spec': {'containers': [{'image': image}]}}}}
    def get(kind, *args):
        return {'deployment': deployment, 'deployments': {'items': []}, 'pods': {'items': [
            pod('live', image='wrong-image' if bad_image else image), pod('evicted', phase='Failed'),
        ]}}[kind]
    monkeypatch.setattr(deployer, 'object_get', get)
    monkeypatch.setattr(deployer, 'pull_and_validate', lambda *args: None)
    monkeypatch.setattr(deployer, 'command', lambda *args: json.dumps({'status': {'id': image}}))
    monkeypatch.setattr(deployer.sys, 'stdin', io.StringIO(''))
    mock_health(monkeypatch, deployer)
    if bad_image:
        with pytest.raises(AssertionError):
            deployer.deploy(revision, digest)
    else:
        deployer.deploy(revision, digest)


@pytest.mark.parametrize('fail_release', [False, True])
def test_release_and_rollback_ignore_terminal_pods(deployer, monkeypatch, tmp_path, fail_release):
    old_revision, new_revision = 'a' * 40, 'b' * 40
    old_image = deployer.REPOSITORY + '@sha256:' + 'a' * 64
    new_digest = 'sha256:' + 'b' * 64
    new_image = deployer.REPOSITORY + '@' + new_digest
    state = {'image': old_image, 'revision': old_revision}
    patches = []
    def get(kind, *args):
        if kind == 'deployment':
            return {'metadata': {'annotations': {'cvtailor.dev/revision': state['revision']}},
                    'spec': {'template': {'spec': {'containers': [{'image': state['image'], 'env': []}]}}}}
        if kind == 'deployments':
            return {'items': []}
        if kind == 'pods':
            return {'items': [pod('evicted', phase='Failed'), pod(
                'live', image=state['image'], ready=not (fail_release and state['image'] == new_image),
            )]}
        raise AssertionError(kind)
    def command(args, payload=None, **kwargs):
        if 'inspecti' in args:
            return json.dumps({'status': {'id': args[-1]}})
        if 'config' in args:
            return json.dumps({'users': [], 'contexts': [{'context': {}}]})
        if 'patch' in args:
            patch = json.loads(payload)
            state['image'] = patch['spec']['template']['spec']['containers'][0]['image']
            state['revision'] = patch['metadata']['annotations']['cvtailor.dev/revision']
            patches.append(state['image'])
        return ''
    monkeypatch.setattr(deployer, 'STATE', tmp_path)
    monkeypatch.setattr(deployer, 'object_get', get)
    monkeypatch.setattr(deployer, 'command', command)
    monkeypatch.setattr(deployer, 'admin', lambda *args, **kwargs: 'synthetic-token')
    monkeypatch.setattr(deployer, 'pull_and_validate', lambda *args: None)
    monkeypatch.setattr(deployer, 'drain', lambda: os.open(tmp_path / 'lock', os.O_CREAT | os.O_RDWR, 0o600))
    monkeypatch.setattr(deployer.sys, 'stdin', io.StringIO(''))
    mock_health(monkeypatch, deployer)
    if fail_release:
        with pytest.raises(AssertionError, match='running and ready'):
            deployer.deploy(new_revision, new_digest)
        assert state['image'] == old_image
        assert patches == [new_image, old_image]
    else:
        deployer.deploy(new_revision, new_digest)
        assert patches == [new_image]
        assert json.loads((tmp_path / 'current-k8s-image.json').read_text())['image'] == new_image
