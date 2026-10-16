"""Controlled single-node migration. Never accesses or restores disk snapshots."""

import argparse
import fcntl
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
PRIVATE = Path(Path('/var/lib/cvtailor-migration/current').read_text().strip())
CLI = ['k3s', 'kubectl']
SOURCE = {'main': REPO / 'data', 'demo': Path('/root/.local/share/cvtailor-recording-demo')}
IMAGE = json.loads((PRIVATE / 'docker-image.json').read_text())['RepoDigests'][0]
PUBLIC = {'APP_ROOT_PATH', 'DEMO_MODE', 'SESSION_TTL_SECONDS', 'BASE_URL', 'APP_BUILD_SHA', 'APP_BUILD_TIMESTAMP',
          'AI_PROVIDER', 'LLM_PROVIDER', 'LLM_FALLBACK_PROVIDER', 'PROFILE_MODE', 'OLLAMA_BASE_URL', 'OLLAMA_MODEL',
          'OLLAMA_CONNECT_TIMEOUT_SECONDS', 'OLLAMA_READ_TIMEOUT_SECONDS', 'OLLAMA_TIMEOUT_SECONDS', 'OLLAMA_KEEP_ALIVE',
          'OLLAMA_MAX_CONCURRENCY', 'OLLAMA_NUM_PREDICT', 'OLLAMA_NUM_CTX', 'GEMINI_MODEL', 'GEMINI_BASE_URL',
          'GEMINI_CONNECT_TIMEOUT_SECONDS', 'GEMINI_READ_TIMEOUT_SECONDS', 'GEMINI_TIMEOUT_SECONDS', 'GEMINI_MAX_RETRIES',
          'LLM_OPERATION_BUDGET_SECONDS', 'REFERENCE_CV_MAX_BYTES', 'PROFILE_PHOTO_MAX_BYTES', 'REQUEST_TIMEOUT_SECONDS',
          'MAX_JOB_DESCRIPTION_CHARS', 'RATE_LIMIT_PER_MINUTE', 'JOB_FETCH_TIMEOUT_SECONDS', 'JOB_FETCH_MAX_BYTES',
          'JOB_FETCH_MAX_REDIRECTS', 'JOB_FETCH_PLAYWRIGHT_ENABLED'}


def run(args, payload=None, timeout=300):
    result = subprocess.run(args, input=payload, text=True, capture_output=True, timeout=timeout)
    if result.returncode:
        raise RuntimeError(f"{args[0]} failed ({result.returncode}): {result.stderr[:1200]}")
    return result.stdout.strip()


def k(*args, payload=None):
    return run(CLI + list(args), payload)


def apply(resources):
    return k('apply', '-f', '-', payload=json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': resources}))


def hashes(path):
    return {str(p.relative_to(path)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(path.rglob('*')) if p.is_file()}


def copy_data(mode, destination, online=False):
    source = SOURCE[mode]
    assert not any(p.is_symlink() for p in source.rglob('*')), 'Inspect data symlinks before copying'
    if destination.exists():
        assert str(destination).startswith(('/var/lib/cvtailor/', str(PRIVATE)))
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    database = destination / 'sessions.sqlite3'
    if online:
        database.unlink(missing_ok=True)
        for suffix in ['-wal', '-shm', '-journal']:
            Path(str(database) + suffix).unlink(missing_ok=True)
        with sqlite3.connect(f'file:{source / "sessions.sqlite3"}?mode=ro', uri=True) as original, sqlite3.connect(database) as target:
            original.backup(target)
    with sqlite3.connect(database) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    if not online:
        assert hashes(source) == hashes(destination), 'Final copy hashes differ'
    for path in [destination, *destination.rglob('*')]:
        os.chown(path, 10001, 10001)
    destination.chmod(0o700)
    return len(hashes(destination))


def settings(mode, port):
    captured = json.loads((PRIVATE / (mode + '-settings.json')).read_text())
    result = {key.upper(): str(value).lower() if isinstance(value, bool) else str(value) for key, value in captured.items() if value is not None}
    result.update(DATA_DIR='/app/data', CVTAILOR_PORT=str(port), PYTHONPATH='/app')
    return result


def resources(namespace, ports, replicas, data_root):
    items = [{'apiVersion': 'v1', 'kind': 'Namespace', 'metadata': {'name': namespace}},
             {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': 'cvtailor-runtime-code', 'namespace': namespace},
              'data': {'runtime.py': (REPO / 'deploy/k8s/production/runtime.py').read_text()}}]
    for mode, port in zip(['main', 'demo'], ports, strict=True):
        name = 'cvtailor' if mode == 'main' else 'cvtailor-demo'
        values = settings(mode, port)
        public = {key: value for key, value in values.items() if key in PUBLIC or key in {'DATA_DIR', 'CVTAILOR_PORT', 'PYTHONPATH'}}
        secret = {key: value for key, value in values.items() if key not in public}
        items.extend([
            {'apiVersion': 'v1', 'kind': 'ConfigMap', 'metadata': {'name': name + '-config', 'namespace': namespace}, 'data': public},
            {'apiVersion': 'v1', 'kind': 'Secret', 'metadata': {'name': name + '-runtime', 'namespace': namespace}, 'type': 'Opaque', 'stringData': secret},
            {'apiVersion': 'v1', 'kind': 'PersistentVolume', 'metadata': {'name': namespace + '-' + mode}, 'spec': {
                'capacity': {'storage': '4Gi' if mode == 'main' else '1Gi'}, 'volumeMode': 'Filesystem', 'accessModes': ['ReadWriteOnce'],
                'persistentVolumeReclaimPolicy': 'Retain', 'storageClassName': 'cvtailor-local',
                'local': {'path': str(data_root / mode)}, 'nodeAffinity': {'required': {'nodeSelectorTerms': [{'matchExpressions': [
                    {'key': 'kubernetes.io/hostname', 'operator': 'In', 'values': ['cvtailor-prod']}]}]}}}},
            {'apiVersion': 'v1', 'kind': 'PersistentVolumeClaim', 'metadata': {'name': name + '-data', 'namespace': namespace}, 'spec': {
                'accessModes': ['ReadWriteOnce'], 'storageClassName': 'cvtailor-local', 'volumeName': namespace + '-' + mode,
                'resources': {'requests': {'storage': '4Gi' if mode == 'main' else '1Gi'}}}},
        ])
        image = IMAGE
        demo_image = PRIVATE / 'demo-image-ref'
        if mode == 'demo' and demo_image.exists():
            image = demo_image.read_text().strip()
        probe = {'httpGet': {'host': '127.0.0.1', 'path': '/health', 'port': port}, 'timeoutSeconds': 10}
        items.append({'apiVersion': 'apps/v1', 'kind': 'Deployment', 'metadata': {'name': name, 'namespace': namespace}, 'spec': {
            'replicas': replicas, 'strategy': {'type': 'Recreate'}, 'revisionHistoryLimit': 3,
            'selector': {'matchLabels': {'app': name}}, 'template': {'metadata': {'labels': {'app': name}}, 'spec': {
                'hostNetwork': True, 'dnsPolicy': 'ClusterFirstWithHostNet', 'automountServiceAccountToken': False,
                'terminationGracePeriodSeconds': 120, 'securityContext': {'runAsNonRoot': True, 'runAsUser': 10001, 'runAsGroup': 10001, 'fsGroup': 10001},
                'containers': [{'name': 'app', 'image': image, 'imagePullPolicy': 'IfNotPresent',
                    'command': ['python', '/opt/cvtailor/runtime.py'],
                    'envFrom': [{'configMapRef': {'name': name + '-config'}}, {'secretRef': {'name': name + '-runtime'}}],
                    'ports': [{'name': 'http', 'containerPort': port, 'hostPort': port, 'hostIP': '127.0.0.1'}],
                    'securityContext': {'allowPrivilegeEscalation': False, 'capabilities': {'drop': ['ALL']}},
                    'resources': {'requests': {'cpu': '100m', 'memory': '256Mi' if mode == 'main' else '192Mi'},
                                  'limits': {'cpu': '1', 'memory': '1Gi' if mode == 'main' else '768Mi'}},
                    'startupProbe': {**probe, 'periodSeconds': 2, 'failureThreshold': 90},
                    'readinessProbe': {**probe, 'periodSeconds': 10, 'failureThreshold': 3},
                    'livenessProbe': {**probe, 'periodSeconds': 15, 'failureThreshold': 6},
                    'volumeMounts': [{'name': 'data', 'mountPath': '/app/data'}, {'name': 'runtime', 'mountPath': '/opt/cvtailor', 'readOnly': True}]}],
                'volumes': [{'name': 'data', 'persistentVolumeClaim': {'claimName': name + '-data'}}, {'name': 'runtime', 'configMap': {'name': 'cvtailor-runtime-code'}}]
            }}}})
    return items


def save_public(items, path):
    public = [item for item in items if item['kind'] != 'Secret']
    path.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List', 'items': public}, indent=2))


def prepare():
    root = Path('/var/lib/cvtailor/staging')
    root.mkdir(parents=True, exist_ok=True)
    for mode in ['main', 'demo']:
        print('Prepared private staging copy', mode, copy_data(mode, root / mode, online=True), 'files', flush=True)
    items = resources('cvtailor-stage', [18010, 18011], 1, root)
    print(apply(items), flush=True)
    save_public(items, PRIVATE / 'stage-public.json')
    for name in ['cvtailor', 'cvtailor-demo']:
        print(k('-n', 'cvtailor-stage', 'rollout', 'status', 'deployment/' + name, '--timeout=240s'), flush=True)


def drain(paths, timeout=900):
    descriptors = []
    try:
        for path in paths:
            file = path / '.deployment-admission.lock'
            descriptor = os.open(file, os.O_CREAT | os.O_RDWR, 0o600)
            os.chown(file, 10001, 10001)
            deadline = time.monotonic() + timeout
            while True:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() > deadline:
                        os.close(descriptor)
                        raise TimeoutError('Inflight HTTP writes did not finish') from None
                    time.sleep(1)
            descriptors.append(descriptor)
        deadline = time.monotonic() + timeout
        while True:
            active = sum(json.loads(file.read_text()).get('status') in {'running', 'queued'} for path in paths for file in (path / 'tasks').glob('*.json'))
            if not active:
                return descriptors
            if time.monotonic() > deadline:
                raise TimeoutError('Active analyses did not finish; no rollout performed')
            time.sleep(2)
    except BaseException:
        for descriptor in descriptors:
            os.close(descriptor)
        raise


def verify(mode, root, port, external=False):
    """Read existing data over HTTP using a short-lived, subsequently revoked session."""
    import base64
    import secrets

    import httpx
    from itsdangerous import TimestampSigner

    captured = json.loads((PRIVATE / (mode + '-settings.json')).read_text())
    token = secrets.token_urlsafe(32)
    digest = hashlib.sha256(token.encode()).hexdigest()
    credential = hashlib.sha256((root / 'auth.json').read_bytes()).hexdigest()
    database = root / 'sessions.sqlite3'
    with sqlite3.connect(database) as connection:
        assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
        connection.execute('INSERT INTO sessions VALUES (?, ?, ?)', (digest, time.time() + 600, credential))
    signed = TimestampSigner(captured['csrf_secret']).sign(base64.b64encode(json.dumps({'id': token}).encode())).decode()
    cookie_name = 'demo_session' if mode == 'demo' else 'session'
    prefix = '/demo' if mode == 'demo' and external else ''
    base = 'https://cv.banas.dev' if external else f'http://127.0.0.1:{port}'
    try:
        with httpx.Client(base_url=base, headers={'Host': 'cv.banas.dev', 'X-Forwarded-Proto': 'https',
                          'Cookie': cookie_name + '=' + signed}, timeout=180) as client:
            for route in ['/health', '/', '/profile', '/skills', '/references', '/history', '/diagnostics', '/health/profile', '/health/skills']:
                response = client.get(prefix + route)
                assert response.status_code == 200, (mode, route, response.status_code)
                assert 'secure' in response.headers.get('set-cookie', '').lower()
            response = client.post(prefix + '/analyze', data={})
            assert response.status_code == 403, ('CSRF protection', response.status_code)
            count = 0
            for metadata in (root / 'generated').glob('*/metadata.json'):
                for kind in ['pdf', 'docx']:
                    path = metadata.parent / ('resume.' + kind)
                    if not path.exists():
                        continue
                    response = client.get(prefix + f'/download/{metadata.parent.name}/{kind}')
                    assert response.status_code == 200
                    assert hashlib.sha256(response.content).hexdigest() == hashlib.sha256(path.read_bytes()).hexdigest()
                    count += 1
            provider = client.get(prefix + '/health/provider')
            assert provider.status_code == 200, ('AI health', provider.status_code)
            # Keep provider details private; they can include deployment configuration.
            (PRIVATE / (mode + '-provider-health.json')).write_text(provider.text)
            os.chmod(PRIVATE / (mode + '-provider-health.json'), 0o600)
            print('PASS authenticated pages, CSRF, SQLite, HTTPS cookies, providers and document hashes:', mode, count, flush=True)
    finally:
        with sqlite3.connect(database) as connection:
            connection.execute('DELETE FROM sessions WHERE digest = ?', (digest,))


def validation():
    import secrets

    root = Path('/var/lib/cvtailor/validation')
    root.mkdir(parents=True, exist_ok=True)
    for mode in ['main', 'demo']:
        path = root / mode
        path.mkdir(exist_ok=True)
        for name in ['master_profile.json', 'skills.json', 'ai_settings.json']:
            shutil.copy2(SOURCE['demo'] / name, path / name)
        for child in [path, *path.rglob('*')]:
            os.chown(child, 10001, 10001)
    items = resources('cvtailor-validation', [18012, 18013], 1, root)
    for item in items:
        name = item.get('metadata', {}).get('name', '')
        if item['kind'] == 'Secret':
            item['stringData'].update(APP_USERNAME='student', APP_PASSWORD=secrets.token_urlsafe(30), CSRF_SECRET=secrets.token_urlsafe(48))
        if item['kind'] == 'ConfigMap' and name.endswith('-config'):
            item['data'].update(PROFILE_MODE='sample', DEMO_MODE='false', APP_ROOT_PATH='', BASE_URL='http://localhost:18012', CVTAILOR_E2E_BASE_URL='http://127.0.0.1:18012' if name == 'cvtailor-config' else 'http://127.0.0.1:18013')
    print(apply(items), flush=True)
    for name in ['cvtailor', 'cvtailor-demo']:
        print(k('-n', 'cvtailor-validation', 'rollout', 'status', 'deployment/' + name, '--timeout=240s'), flush=True)


def cutover():
    """One maintenance window; failures before reopening traffic restore old processes."""
    import tarfile

    namespace = 'cvtailor-prod'
    root = Path('/var/lib/cvtailor/production')
    assert not root.exists(), 'Production data already exists; inspect rather than overwrite'
    config = Path('/etc/nginx/sites-enabled/cv.banas.dev.conf').resolve()
    original = config.read_text()
    (PRIVATE / 'nginx-site.original.conf').write_text(original)
    os.chmod(PRIVATE / 'nginx-site.original.conf', 0o600)
    marker = Path('/run/cvtailor-maintenance')
    assert not marker.exists()
    insertion = '    if (-f /run/cvtailor-maintenance) { return 503; }\n'
    changed = original.replace('    listen 443 ssl http2;\n', '    listen 443 ssl http2;\n' + insertion, 1)
    assert changed != original
    config.write_text(changed)
    try:
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    except BaseException:
        config.write_text(original)
        raise
    marker.touch(mode=0o644)
    print('Maintenance enabled; waiting for existing tasks', flush=True)
    stopped = False
    descriptors = []
    started = time.time()
    try:
        # Old applications do not have admission middleware; Nginx now blocks all public traffic.
        descriptors = drain(list(SOURCE.values()), timeout=600)
        stopped = True
        run(['docker', 'stop', '--time', '120', 'cv-tailor'])
        run(['systemctl', 'stop', 'cvtailor-recording-demo.service'])
        stopped = True
        inventory = {}
        for mode in ['main', 'demo']:
            before = hashes(SOURCE[mode])
            archive = PRIVATE / (mode + '-before-cutover.tar.gz')
            assert not archive.exists()
            with os.fdopen(os.open(archive, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
                with tarfile.open(fileobj=handle, mode='w:gz') as backup:
                    backup.add(SOURCE[mode], arcname=mode)
            (PRIVATE / (mode + '-before-cutover-hashes.json')).write_text(json.dumps(before, indent=2))
            root.mkdir(parents=True, exist_ok=True)
            count = copy_data(mode, root / mode)
            inventory[mode] = {'files': count, 'archive': str(archive), 'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
        items = resources(namespace, [18000, 18001], 1, root)
        revision = json.loads((PRIVATE / 'docker-image.json').read_text())['Config']['Labels']['org.opencontainers.image.revision']
        for item in items:
            if item['kind'] == 'Deployment' and item['metadata']['name'] == 'cvtailor':
                item['metadata']['annotations'] = {'cvtailor.dev/revision': revision}
        print(apply(items), flush=True)
        save_public(items, PRIVATE / 'production-public.json')
        for name in ['cvtailor', 'cvtailor-demo']:
            print(k('-n', namespace, 'rollout', 'status', 'deployment/' + name, '--timeout=180s'), flush=True)
        for mode, port in [('main', 18000), ('demo', 18001)]:
            verify(mode, root / mode, port)
        # Keep stopped predecessors from claiming the same loopback ports after reboot.
        run(['docker', 'update', '--restart=no', 'cv-tailor'])
        run(['systemctl', 'disable', 'cvtailor-recording-demo.service'])
        inventory.update(completed_at=time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), maintenance_seconds=round(time.time() - started), revision=revision)
        (PRIVATE / 'cutover-result.json').write_text(json.dumps(inventory, indent=2))
    except BaseException:
        print('Cutover failed before public writes; restoring previous deployment', flush=True)
        existing = k('get', 'namespace', namespace, '--ignore-not-found', '-o', 'name')
        if existing:
            k('-n', namespace, 'scale', 'deployment', '--all', '--replicas=0')
            k('-n', namespace, 'wait', '--for=delete', 'pod', '--all', '--timeout=120s')
        if stopped:
            run(['docker', 'update', '--restart=unless-stopped', 'cv-tailor'])
            run(['docker', 'start', 'cv-tailor'])
            run(['systemctl', 'enable', '--now', 'cvtailor-recording-demo.service'])
        raise
    finally:
        for descriptor in descriptors:
            os.close(descriptor)
        marker.unlink(missing_ok=True)
        # Original Nginx routing and TLS remain byte-for-byte unchanged after this window.
        config.write_text(original)
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
    print('Production traffic now served by K3s', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['prepare', 'verify-stage', 'validation', 'cutover', 'verify-production'])
    args = parser.parse_args()
    if args.action == 'prepare':
        prepare()
    elif args.action == 'verify-stage':
        for mode, port in [('main', 18010), ('demo', 18011)]:
            verify(mode, Path('/var/lib/cvtailor/staging') / mode, port)
    elif args.action == 'validation':
        validation()
    elif args.action == 'cutover':
        cutover()
    elif args.action == 'verify-production':
        for mode, port in [('main', 18000), ('demo', 18001)]:
            verify(mode, Path('/var/lib/cvtailor/production') / mode, port, external=True)


if __name__ == '__main__':
    main()
