#!/usr/bin/env python3
"""Read-only Kubernetes isolation inspection. Output excludes secret values and CV data."""
import argparse
import json
import subprocess
from datetime import UTC, datetime


def inspect(deployments, config, policies):
    issues = []
    by_name = {item['metadata']['name']: item for item in deployments['items']}
    policy_names = {item['metadata']['name'] for item in policies['items']}
    data = config.get('data', {})
    if data.get('PROCESSING_REQUIRED', '').lower() != 'true':
        issues.append('PROCESSING_REQUIRED is not enabled in cvtailor-config')
    urls = [data.get(key) for key in ('PROCESSING_URL', 'DEMO_PROCESSING_URL')]
    if not all(urls) or urls[0] == urls[1]:
        issues.append('Independent owner/demo processing URLs are not configured')
    results = []
    for account in ('owner', 'demo'):
        name = 'cvtailor-processing-' + account
        item = by_name.get(name)
        if item is None:
            issues.append(name + ' deployment is missing')
            continue
        spec = item['spec']['template']['spec']
        container = spec['containers'][0]
        security = spec.get('securityContext', {}) | container.get('securityContext', {})
        checks = {
            'ready': item.get('status', {}).get('readyReplicas', 0) >= 1,
            'separate_network': not spec.get('hostNetwork', False),
            'separate_pid_namespace': not spec.get('hostPID', False) and not spec.get('shareProcessNamespace', False),
            'no_service_token': spec.get('automountServiceAccountToken') is False,
            'nonroot': security.get('runAsNonRoot') is True and security.get('runAsUser', 0) > 0,
            'readonly_root': security.get('readOnlyRootFilesystem') is True,
            'no_privilege_escalation': security.get('allowPrivilegeEscalation') is False and not security.get('privileged', False),
            'dropped_capabilities': 'ALL' in security.get('capabilities', {}).get('drop', []),
            'scratch_only': spec.get('volumes') == [{'name': 'scratch', 'emptyDir': {'sizeLimit': '256Mi'}}]
                and all(m['name'] == 'scratch' and m['mountPath'] == '/tmp' for m in container.get('volumeMounts', [])),
            'bounded_resources': container.get('resources', {}).get('limits') == {'cpu': '1', 'memory': '768Mi'},
            'no_bulk_environment': not container.get('envFrom'),
            'environment_allowlist': {entry['name'] for entry in container.get('env', [])} <= {
                'PROCESSING_TOKEN', 'PROCESSING_CONTAINER_ISOLATED', 'HOME', 'PYTHONUNBUFFERED', 'PYTHONDONTWRITEBYTECODE'},
            'own_token_reference': any(entry['name'] == 'PROCESSING_TOKEN' and
                entry.get('valueFrom', {}).get('secretKeyRef') == {'name': 'cvtailor-processing', 'key': account}
                for entry in container.get('env', [])),
            'policy_declared': name in policy_names,
        }
        issues.extend(name + ': ' + key for key, passed in checks.items() if not passed)
        results.append({'account': account, 'image': container['image'], 'checks': checks})
    return {'checked_at': datetime.now(UTC).isoformat(), 'workers': results, 'issues': issues,
            'scope': 'Live deployment/configuration inspection only. Does not prove CNI enforcement or parser/kernel behavior.'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--namespace', default='cvtailor-prod')
    parser.add_argument('--kubectl', default='k3s', choices=['k3s', 'kubectl'])
    args = parser.parse_args()
    prefix = ['k3s', 'kubectl'] if args.kubectl == 'k3s' else ['kubectl']
    def get(kind, name=None):
        command = [*prefix, '-n', args.namespace, 'get', kind, *([name] if name else []), '-o', 'json']
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError('Cannot inspect ' + kind + '; check read-only cluster access')
        return json.loads(result.stdout)
    report = inspect(get('deployments'), get('configmap', 'cvtailor-config'), get('networkpolicies'))
    print(json.dumps(report, indent=2))
    return bool(report['issues'])


if __name__ == '__main__':
    raise SystemExit(main())
