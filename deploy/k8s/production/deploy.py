#!/usr/bin/python3
"""Root-owned SSH deployment entrypoint: pinned images, drain, health, rollback.

The GitHub identity never receives a kubeconfig or registry token on argv.
Install as /usr/local/sbin/cvtailor-deploy, owned by root, mode 0755.
"""

import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

NAMESPACE = 'cvtailor-prod'
REPOSITORY = 'ghcr.io/rafalbanas/ai-resume-tailoring-platform'
STATE = Path('/var/lib/cvtailor-cd')
DATA = Path('/var/lib/cvtailor/production/main')


def command(arguments, payload=None, timeout=300):
    result = subprocess.run(arguments, input=payload, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        # Registry responses and credential-bearing stdin must never reach logs.
        raise RuntimeError('Command failed: ' + ' '.join(arguments[:4]))
    return result.stdout.strip()


def admin(*arguments, payload=None):
    return command(['k3s', 'kubectl', '-n', NAMESPACE, *arguments], payload)


def object_get(*arguments):
    return json.loads(admin('get', *arguments, '-o', 'json'))


def drain(timeout=900):
    descriptor = os.open(DATA / '.deployment-admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
    os.fchown(descriptor, 10001, 10001)
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('Inflight requests did not finish; deployment refused') from None
                time.sleep(1)
        while any(json.loads(path.read_text()).get('status') in {'queued', 'running'} for directory in (DATA, DATA.parent / 'demo') for path in (directory / 'tasks').glob('*.json')):
            if time.monotonic() >= deadline:
                raise TimeoutError('Active analyses did not finish; deployment refused')
            time.sleep(2)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def healthy():
    with urllib.request.urlopen('http://127.0.0.1:18000/health', timeout=10) as response:
        assert response.status == 200
    pods = object_get('pods', '-l', 'app=cvtailor')['items']
    ready = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp') and
             any(condition['type'] == 'Ready' and condition['status'] == 'True' for condition in pod.get('status', {}).get('conditions', []))]
    assert len(ready) == 1, 'Exactly one ready production pod is required'


def pull_and_validate(image, revision, token):
    authentication = {'auths': {}}
    if token:
        authentication['auths']['ghcr.io'] = {'auth': base64.b64encode(('rafalbanas:' + token).encode()).decode()}
    secret = {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': 'cvtailor-ghcr', 'namespace': NAMESPACE},
              'type': 'kubernetes.io/dockerconfigjson', 'stringData': {'.dockerconfigjson': json.dumps(authentication)}}
    # Server-side apply avoids storing a second credential copy in last-applied annotations.
    admin('apply', '--server-side', '--field-manager=cvtailor-cd', '-f', '-', payload=json.dumps(secret))
    name = 'cvtailor-image-check-' + revision[:12]
    admin('delete', 'pod', name, '--ignore-not-found', '--wait=true')
    pod = {'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {'name': name, 'namespace': NAMESPACE}, 'spec': {
        'restartPolicy': 'Never', 'automountServiceAccountToken': False, 'imagePullSecrets': [{'name': 'cvtailor-ghcr'}],
        'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001},
        'containers': [{'name': 'check', 'image': image, 'imagePullPolicy': 'IfNotPresent', 'command': ['python', '-c', 'pass'],
                        'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                        'resources': {'requests': {'cpu': '10m', 'memory': '32Mi'}, 'limits': {'cpu': '200m', 'memory': '128Mi'}}}]}}
    try:
        admin('create', '-f', '-', payload=json.dumps(pod))
        admin('wait', '--for=jsonpath={.status.phase}=Succeeded', 'pod/' + name, '--timeout=240s')
        information = json.loads(command(['k3s', 'crictl', 'inspecti', image]))
        labels = information['info']['imageSpec']['config'].get('Labels', {})
        assert labels.get('org.opencontainers.image.revision') == revision, 'Image revision does not match requested commit'
    finally:
        admin('delete', 'pod', name, '--ignore-not-found', '--wait=false')


def deploy(revision, digest):
    image = REPOSITORY + '@' + digest
    token = sys.stdin.readline(8193).strip()
    assert len(token) <= 8192
    pull_and_validate(image, revision, token)
    previous = object_get('deployment', 'cvtailor')
    previous_image = previous['spec']['template']['spec']['containers'][0]['image']
    processors = {item['metadata']['name']: item['spec']['template']['spec']['containers'][0]['image']
                  for item in object_get('deployments')['items'] if item['metadata']['name'] in {'cvtailor-processing-owner', 'cvtailor-processing-demo'}}
    previous_environment = previous['spec']['template']['spec']['containers'][0].get('env', [])
    previous_revision = previous['metadata'].get('annotations', {}).get('cvtailor.dev/revision', '')
    if previous_image == image and previous_revision == revision:
        healthy()
        information = json.loads(command(['k3s', 'crictl', 'inspecti', image]))['status']
        valid_ids = [information['id'], *information.get('repoDigests', [])]
        pods = object_get('pods', '-l', 'app=cvtailor')['items']
        running = [pod for pod in pods if not pod['metadata'].get('deletionTimestamp')]
        assert len(running) == 1 and running[0]['status']['containerStatuses'][0]['imageID'] in valid_ids
        print('Exact approved image is already healthy in Kubernetes; no rollout required.')
        return
    # The short-lived identity can only get/patch/watch this one Deployment.
    identity = admin('create', 'token', 'cvtailor-deployer', '--duration=20m')
    config = json.loads(command(['k3s', 'kubectl', 'config', 'view', '--raw', '--minify', '-o', 'json']))
    config['users'] = [{'name': 'cvtailor-deployer', 'user': {'token': identity}}]
    config['contexts'][0]['context'].update(user='cvtailor-deployer', namespace=NAMESPACE)
    descriptor = drain()
    try:
        with tempfile.TemporaryDirectory(prefix='cvtailor-cd-', dir=STATE) as directory:
            kubeconfig = Path(directory) / 'config'
            kubeconfig.write_text(json.dumps(config))
            kubeconfig.chmod(0o600)
            cli = ['k3s', 'kubectl', '--kubeconfig', str(kubeconfig), '-n', NAMESPACE]

            def update_processors(images):
                for name, processor_image in images.items():
                    # Fixed isolated deployments only; images are validated digests.
                    admin('set', 'image', 'deployment/' + name, 'processor=' + processor_image)
                    admin('rollout', 'status', 'deployment/' + name, '--timeout=240s')

            def release(target_image, target_revision, environment):
                patch = {'metadata': {'annotations': {'cvtailor.dev/revision': target_revision}}, 'spec': {'template': {'spec': {
                    'imagePullSecrets': [{'name': 'cvtailor-ghcr'}], 'containers': [{'name': 'app', 'image': target_image,
                        'env': [{'$patch': 'replace'}, *environment]}]}}}}
                command(cli + ['patch', 'deployment', 'cvtailor', '--type=strategic', '--patch-file=/dev/stdin'], json.dumps(patch))
                command(cli + ['rollout', 'status', 'deployment/cvtailor', '--timeout=240s'])
                healthy()
                current = object_get('deployment', 'cvtailor')
                assert current['spec']['template']['spec']['containers'][0]['image'] == target_image
                information = json.loads(command(['k3s', 'crictl', 'inspecti', target_image]))['status']
                valid_ids = [information['id'], *information.get('repoDigests', [])]
                running = object_get('pods', '-l', 'app=cvtailor')['items']
                ready = [pod for pod in running if not pod['metadata'].get('deletionTimestamp')]
                assert len(ready) == 1
                assert ready[0]['status']['containerStatuses'][0]['imageID'] in valid_ids, 'Running image differs from validated image'

            try:
                update_processors({name: image for name in processors})
                environment = [entry for entry in previous_environment if entry['name'] not in {'APP_BUILD_SHA', 'APP_BUILD_TIMESTAMP'}]
                environment.extend([{'name': 'APP_BUILD_SHA', 'value': revision},
                                    {'name': 'APP_BUILD_TIMESTAMP', 'value': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}])
                release(image, revision, environment)
            except BaseException:
                print('Deployment failed; restoring previous pinned image.', file=sys.stderr, flush=True)
                update_processors(processors)
                release(previous_image, previous_revision, previous_environment)
                print('Previous image restored.', file=sys.stderr, flush=True)
                raise
        (STATE / 'previous-k8s-image.json').write_text(json.dumps({'image': previous_image, 'revision': previous_revision}))
        (STATE / 'current-k8s-image.json').write_text(json.dumps({'image': image, 'revision': revision}))
        print('Deployed ' + revision + ' to Kubernetes successfully.')
    finally:
        os.close(descriptor)


def main():
    os.environ['PATH'] = '/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
    if sys.argv[1:] == ['status']:
        print(object_get('deployment', 'cvtailor')['metadata']['annotations']['cvtailor.dev/revision'])
        return
    if len(sys.argv) != 3 or not re.fullmatch('[a-f0-9]{40}', sys.argv[1]) or not re.fullmatch('sha256:[a-f0-9]{64}', sys.argv[2]):
        raise SystemExit('Invalid revision or image digest')
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'deploy.lock').open('w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('Another deployment is running') from None
        deploy(*sys.argv[1:])


if __name__ == '__main__':
    main()
