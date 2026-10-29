"""Read-only deployment evidence and dependency drift must not be mistaken for protection."""
import importlib.util
import json
from pathlib import Path

import pytest


def module(path):
    spec = importlib.util.spec_from_file_location(Path(path).stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_environment_check_rejects_wrong_python_and_stale_pypdf():
    checker = module('scripts/check_environment.py')
    pinned = {}
    for line in Path('requirements.txt').read_text().splitlines():
        if '==' in line:
            name, version = line.split('==')
            pinned[name.split('[')[0]] = version
    assert checker.check(python_version='3.14', package_version=pinned.__getitem__) == []
    expected_pypdf = pinned['pypdf']
    pinned['pypdf'] = '0.0.0'
    problems = checker.check(python_version='3.12', package_version=pinned.__getitem__)
    assert len(problems) == 2
    assert f'pypdf: expected {expected_pypdf}, found 0.0.0' in problems
    assert any('Python' in issue and '3.14' in issue for issue in problems)


def deployment_inputs():
    resources = json.loads(Path('deploy/k8s/production/processing.json').read_text())['items']
    deployments = [item for item in resources if item['kind'] == 'Deployment']
    for item in deployments:
        item['status'] = {'readyReplicas': 1}
    policies = [item for item in resources if item['kind'] == 'NetworkPolicy']
    config = {'data': {'PROCESSING_REQUIRED': 'true', 'PROCESSING_URL': 'http://owner:8080', 'DEMO_PROCESSING_URL': 'http://demo:8080'}}
    return {'items': deployments}, config, {'items': policies}


def test_inspector_reports_missing_migration_without_reading_secrets():
    inspector = module('scripts/audit_processing_deployment.py')
    report = inspector.inspect({'items': []}, {'data': {}}, {'items': []})
    assert len(report['issues']) == 4
    assert not report['workers']
    assert 'Does not prove CNI' in report['scope']


@pytest.mark.parametrize('change', ['none', 'volume', 'root', 'host-network', 'shared-token', 'secret-environment'])
def test_inspector_checks_live_specs_and_never_returns_environment_values(change):
    inspector = module('scripts/audit_processing_deployment.py')
    deployments, config, policies = deployment_inputs()
    spec = deployments['items'][0]['spec']['template']['spec']
    container = spec['containers'][0]
    if change == 'volume':
        spec['volumes'].append({'name': 'private', 'hostPath': {'path': '/private'}})
    elif change == 'root':
        spec['securityContext']['runAsUser'] = 0
    elif change == 'host-network':
        spec['hostNetwork'] = True
    elif change == 'shared-token':
        next(entry for entry in container['env'] if entry['name'] == 'PROCESSING_TOKEN')['valueFrom']['secretKeyRef']['key'] = 'demo'
    elif change == 'secret-environment':
        container['env'].append({'name': 'GEMINI_API_KEY', 'value': 'synthetic-secret-never-print'})
    report = inspector.inspect(deployments, config, policies)
    assert bool(report['issues']) == (change != 'none'), report
    assert 'synthetic-secret-never-print' not in json.dumps(report)
