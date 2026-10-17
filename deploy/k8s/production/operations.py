#!/usr/bin/python3
"""Private application/cluster backups and lightweight local monitoring."""

import base64
import fcntl
import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path

DATA = Path('/var/lib/cvtailor/production')
STORE = Path('/storage/cvtailor-k3s-backups')
STATE = Path('/var/lib/cvtailor-operations')
CLI = ['k3s', 'kubectl', '-n', 'cvtailor-prod']


def kubernetes(*arguments):
    result = subprocess.run(CLI + list(arguments), capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError('Kubernetes query failed')
    return json.loads(result.stdout)


def hashes(root):
    return {str(path.relative_to(root)): hashlib.sha256(path.read_bytes()).hexdigest() for path in root.rglob('*') if path.is_file()}


def sql_copy(source, target):
    with sqlite3.connect(f'file:{source}?mode=ro', uri=True) as original, sqlite3.connect(target) as copied:
        original.backup(copied)
        assert copied.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def backup():
    # Refuse to fill the root disk if the separate storage mount disappears.
    assert os.path.ismount('/storage'), 'Separate storage is not mounted'
    assert os.stat('/storage').st_dev != os.stat('/').st_dev
    STORE.mkdir(mode=0o700, exist_ok=True)
    assert not STORE.is_symlink() and STORE.stat().st_uid == 0
    STORE.chmod(0o700)
    stamp = time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())
    descriptors = []
    try:
        with tempfile.TemporaryDirectory(prefix='cvtailor-backup-', dir=STATE) as name:
            staging = Path(name)
            deadline = time.monotonic() + 30
            for mode in ['main', 'demo']:
                descriptor = os.open(DATA / mode / '.deployment-admission.lock', os.O_CREAT | os.O_RDWR, 0o600)
                os.fchown(descriptor, 10001, 10001)
                descriptors.append(descriptor)
                while True:
                    try:
                        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() > deadline:
                            raise TimeoutError('Inflight requests prevented backup') from None
                        time.sleep(1)
            if any(json.loads(path.read_text()).get('status') in {'running', 'queued'} for mode in ['main', 'demo'] for path in (DATA / mode / 'tasks').glob('*.json')):
                raise RuntimeError('Active AI tasks; backup deferred for a later retry')
            for mode in ['main', 'demo']:
                target = staging / mode
                shutil.copytree(DATA / mode, target)
                for suffix in ['', '-wal', '-shm', '-journal']:
                    (target / ('sessions.sqlite3' + suffix)).unlink(missing_ok=True)
                sql_copy(DATA / mode / 'sessions.sqlite3', target / 'sessions.sqlite3')
                if (DATA / mode / 'resource_usage.sqlite3').exists():
                    sql_copy(DATA / mode / 'resource_usage.sqlite3', target / 'resource_usage.sqlite3')
            # Release admission as soon as a consistent application copy exists.
            for descriptor in descriptors:
                os.close(descriptor)
            descriptors.clear()
            cluster = staging / 'cluster'
            cluster.mkdir()
            server = Path('/var/lib/rancher/k3s/server')
            sql_copy(server / 'db/state.db', cluster / 'state.db')
            for item in ['token', 'cred', 'tls']:
                source = server / item
                if source.is_dir():
                    shutil.copytree(source, cluster / item)
                else:
                    shutil.copy2(source, cluster / item)
            config = staging / 'configuration'
            config.mkdir()
            for source, target in [('/etc/rancher/k3s', 'k3s'), ('/etc/cvtailor', 'cvtailor'),
                                   ('/etc/nginx/sites-enabled/cv.banas.dev.conf', 'nginx.conf'),
                                   ('/etc/nginx/ssl', 'nginx-tls'),
                                   ('/etc/systemd/system/k3s.service.d', 'k3s-service.d'),
                                   ('/usr/local/sbin/cvtailor-deploy', 'cvtailor-deploy'),
                                   ('/usr/local/bin/cvtailor-cd-ssh', 'cvtailor-cd-ssh')]:
                path = Path(source)
                if source.endswith('k3s.service.d') and not path.exists():
                    continue
                if path.is_dir():
                    shutil.copytree(path, config / target)
                else:
                    shutil.copy2(path, config / target)
            for kind in ['deployment', 'pv', 'pvc', 'configmap', 'secret', 'serviceaccount', 'role', 'rolebinding']:
                (config / (kind + '.json')).write_text(json.dumps(kubernetes('get', kind, '-o', 'json')))
            manifest = hashes(staging)
            (staging / 'hashes.json').write_text(json.dumps(manifest, indent=2))
            target = STORE / ('daily-' + stamp + '.tar.gz')
            with os.fdopen(os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as handle:
                with tarfile.open(fileobj=handle, mode='w:gz') as archive:
                    archive.add(staging, arcname='.')
            # Verify the archive bytes, all member hashes, and the recovered SQLite databases.
            verify_backup(target)
            if time.gmtime().tm_wday == 6:
                os.link(target, STORE / ('weekly-' + stamp + '.tar.gz'))
            for prefix, keep in [('daily', 7), ('weekly', 4)]:
                old = sorted(path for path in STORE.iterdir() if re.fullmatch(prefix + r'-\d{8}T\d{6}Z\.tar\.gz', path.name))
                for path in old[:-keep]:
                    path.unlink()
            (STATE / 'last-backup.json').write_text(json.dumps({'archive': str(target), 'sha256': hashlib.sha256(target.read_bytes()).hexdigest(), 'files': len(manifest), 'verified': True}))
            print('Backup and isolated restore verification passed:', target)
    finally:
        for descriptor in descriptors:
            os.close(descriptor)


def verify_backup(archive):
    with tempfile.TemporaryDirectory(prefix='cvtailor-restore-check-', dir=STATE) as name:
        root = Path(name)
        with tarfile.open(archive) as handle:
            # Cluster TLS symlinks remain inside the archive tree; no application symlinks are allowed.
            handle.extractall(root, filter='data')
        expected = json.loads((root / 'hashes.json').read_text())
        actual = hashes(root)
        actual.pop('hashes.json')
        assert actual == expected, 'Recovered archive hashes differ'
        for file in [root / 'main/sessions.sqlite3', root / 'demo/sessions.sqlite3', root / 'cluster/state.db']:
            with sqlite3.connect(f'file:{file}?mode=ro', uri=True) as connection:
                assert connection.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'


def monitor():
    issues = []
    result = {'checked_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    old_file = STATE / 'monitor.json'
    old = json.loads(old_file.read_text()) if old_file.exists() else {}
    pods = kubernetes('get', 'pods', '-o', 'json')['items']
    restarts = {}
    deployments = kubernetes('get', 'deployments', '-o', 'json')['items']
    desired = {item['metadata']['name']: item['spec'].get('replicas', 1) for item in deployments}
    for app in ['cvtailor', 'cvtailor-demo', *sorted(name for name in desired if name.startswith('cvtailor-processing-'))]:
        active = [pod for pod in pods if pod['metadata'].get('labels', {}).get('app') == app and not pod['metadata'].get('deletionTimestamp')]
        if len(active) != desired.get(app, 1) or not all(any(c['type'] == 'Ready' and c['status'] == 'True' for c in pod['status'].get('conditions', [])) for pod in active):
            issues.append(app + ': pod not ready')
        for pod in active:
            for container in pod['status'].get('containerStatuses', []):
                key = pod['metadata']['uid'] + ':' + container['name']
                restarts[key] = container['restartCount']
                if restarts[key] > old.get('restarts', {}).get(key, 0):
                    issues.append(app + ': new container restart')
                if container.get('lastState', {}).get('terminated', {}).get('reason') == 'OOMKilled':
                    issues.append(app + ': OOMKilled')
    for claim in kubernetes('get', 'pvc', '-o', 'json')['items']:
        if claim['status'].get('phase') != 'Bound':
            issues.append('PVC not bound: ' + claim['metadata']['name'])
    memory = {line.split(':')[0]: int(line.split()[1]) for line in Path('/proc/meminfo').read_text().splitlines() if len(line.split()) >= 2}
    result['memory_available_mib'] = memory.get('MemAvailable', 0) // 1024
    if result['memory_available_mib'] < 300:
        issues.append('Host available memory below 300 MiB')
    for mode in ['main', 'demo']:
        for file in (DATA / mode / 'tasks').glob('*.json'):
            task = json.loads(file.read_text())
            if task.get('status') in {'queued', 'running'} and time.time() - file.stat().st_mtime > 1800:
                issues.append(mode + ': task inactive for over 30 minutes')
                break
    for path in ['/', '/storage']:
        space = shutil.disk_usage(path)
        if space.free / space.total < 0.15:
            issues.append('Disk free below 15%: ' + path)
    for path in ['/health']:
        try:
            with urllib.request.urlopen('https://cv.banas.dev' + path, timeout=15) as response:
                assert response.status == 200
        except Exception:
            issues.append('HTTPS unavailable: ' + path)
    try:
        secret = kubernetes('get', 'secret', 'cvtailor-runtime', '-o', 'json')['data']
        key = base64.b64decode(secret.get('GEMINI_API_KEY', '')).decode()
        with urllib.request.urlopen('http://127.0.0.1:11434/api/tags', timeout=10) as response:
            assert response.status == 200
        if key:
            request = urllib.request.Request('https://generativelanguage.googleapis.com/v1beta/models', headers={'x-goog-api-key': key})
            with urllib.request.urlopen(request, timeout=15) as response:
                assert response.status == 200
    except Exception:
        issues.append('AI provider health check failed')
    backup_status = STATE / 'last-backup.json'
    if not backup_status.exists() or time.time() - backup_status.stat().st_mtime > 30 * 3600:
        issues.append('Verified backup older than 30 hours')
    result.update(issues=issues, restarts=restarts)
    old_file.write_text(json.dumps(result, indent=2))
    if issues != old.get('issues', []):
        print('CVTailor monitoring:', '; '.join(issues) if issues else 'all checks recovered')
    return bool(issues)


def main():
    os.umask(0o077)
    STATE.mkdir(mode=0o700, exist_ok=True)
    with (STATE / 'operations.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if sys.argv[1:] == ['backup']:
            with Path('/var/lib/cvtailor-cd/deploy.lock').open('a') as deployment_lock:
                fcntl.flock(deployment_lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                backup()
        elif sys.argv[1:] == ['monitor']:
            raise SystemExit(monitor())
        else:
            raise SystemExit('Usage: cvtailor-operations {backup|monitor}')


if __name__ == '__main__':
    main()
