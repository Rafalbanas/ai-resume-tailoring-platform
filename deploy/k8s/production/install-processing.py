#!/usr/bin/python3
"""One-time, reviewable processing migration. Run as cluster admin with an exact image digest."""
import json
import os
import re
import secrets
import subprocess
import sys
from pathlib import Path

from deploy import drain

CLI = ['k3s', 'kubectl', '-n', 'cvtailor-prod']


def command(*args, value=None):
    result = subprocess.run([*CLI, *args], input=json.dumps(value) if value is not None else None,
                            capture_output=True, text=True, timeout=300)
    if result.returncode:
        raise RuntimeError('Processing migration command failed: ' + ' '.join(args[:3]))
    return result.stdout


def install(image):
    if not re.fullmatch(r'ghcr.io/rafalbanas/ai-resume-tailoring-platform@sha256:[a-f0-9]{64}', image):
        raise ValueError('An exact application image digest is required')
    exists = command('get', 'secret', 'cvtailor-processing', '--ignore-not-found', '-o', 'name').strip()
    if not exists:
        command('apply', '--server-side', '--field-manager=cvtailor-processing', '-f', '-', value={
            'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'cvtailor-processing', 'namespace': 'cvtailor-prod'},
            'stringData': {name: secrets.token_urlsafe(48) for name in ('owner', 'demo')}})
    manifest = json.loads(Path(__file__).with_name('processing.json').read_text())
    for item in manifest['items']:
        if item['kind'] == 'Deployment':
            item['spec']['template']['spec']['containers'][0]['image'] = image
    command('apply', '--server-side', '--field-manager=cvtailor-processing', '-f', '-', value=manifest)
    for account in ('owner', 'demo'):
        command('rollout', 'status', 'deployment/cvtailor-processing-' + account, '--timeout=240s')
    command('patch', 'configmap', 'cvtailor-config', '--type=merge', '-p', json.dumps({'data': {
        'PROCESSING_REQUIRED': 'true',
        'PROCESSING_URL': 'http://cvtailor-processing-owner:8080',
        'DEMO_PROCESSING_URL': 'http://cvtailor-processing-demo:8080'}}))
    command('patch', 'deployment', 'cvtailor', '--type=strategic', '-p', json.dumps({'spec': {'template': {'spec': {'containers': [{'name': 'app', 'env': [
        {'name': 'PROCESSING_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'cvtailor-processing', 'key': 'owner'}}},
        {'name': 'DEMO_PROCESSING_TOKEN', 'valueFrom': {'secretKeyRef': {'name': 'cvtailor-processing', 'key': 'demo'}}},
    ]}]}}}}))
    command('rollout', 'status', 'deployment/cvtailor', '--timeout=240s')
    print('Independent processing services are ready; no account data was moved and no login credentials changed.')


if __name__ == '__main__':
    descriptor = drain()
    try:
        install(sys.argv[1])
    finally:
        os.close(descriptor)
