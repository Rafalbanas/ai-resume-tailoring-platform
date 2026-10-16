"""Move only K3s containerd storage; Docker and application SQLite stay local."""

import fcntl
import json
import os
import signal
import subprocess
import time
import urllib.request
from pathlib import Path

SOURCE = Path('/var/lib/rancher/k3s/agent/containerd')
TARGET = Path('/storage/cvtailor-k3s-runtime/containerd')
SAVED = SOURCE.with_name('containerd.before-storage')
DROPIN = Path('/etc/systemd/system/k3s.service.d/cvtailor-storage.conf')
CLI = ['k3s', 'kubectl', '-n', 'cvtailor-prod']
CRI = ['k3s', 'crictl', '--runtime-endpoint=unix:///run/k3s/containerd/containerd.sock']


def run(arguments, timeout=300, check=True):
    result = subprocess.run(arguments, text=True, capture_output=True, timeout=timeout)
    if check and result.returncode:
        raise RuntimeError(f'Command failed: {arguments[:3]}: {result.stderr[:500]}')
    return result


def wait_gone(pid, timeout=30):
    deadline = time.monotonic() + timeout
    while Path(f'/proc/{pid}').exists():
        if time.monotonic() > deadline:
            raise TimeoutError('K3s process did not stop')
        time.sleep(0.2)



def runtime_pids():
    found = []
    for comm in Path('/proc').glob('[0-9]*/comm'):
        try:
            if (comm.read_text().strip() == 'containerd' and
                    '/system.slice/k3s.service' in (comm.parent / 'cgroup').read_text() and
                    str((comm.parent / 'exe').resolve()).startswith('/var/lib/rancher/k3s/data/')):
                found.append(int(comm.parent.name))
        except OSError:
            continue
    return found


def stop_runtime():
    # All commands use the K3s socket; the normal Docker runtime is excluded.
    containers = run(CRI + ['ps', '-q'], check=False).stdout.split()
    sandboxes = run(CRI + ['pods', '-q'], check=False).stdout.split()
    run(['systemctl', 'stop', 'k3s'])
    if Path('/run/k3s/containerd/containerd.sock').exists() and runtime_pids():
        for command, ids in [('stop', containers), ('stopp', sandboxes)]:
            for identifier in ids:
                run(CRI + [command, identifier], timeout=30, check=False)
    # A stopped K3s server can leave shims alive. Identify them by executable
    # provenance, namespace, socket, and task id before terminating their tree.
    shims = []
    for file in Path('/proc').glob('[0-9]*/cmdline'):
        try:
            arguments = file.read_bytes().split(b'\0')
            executable = str((file.parent / 'exe').resolve())
            if (executable.startswith('/var/lib/rancher/k3s/data/') and
                    b'/run/k3s/containerd/containerd.sock' in arguments and
                    b'k8s.io' in arguments and b'-id' in arguments):
                identifier = arguments[arguments.index(b'-id') + 1].decode()
                if len(identifier) == 64:
                    shims.append((int(file.parent.name), identifier))
        except (OSError, ValueError, IndexError):
            continue
    for pid, identifier in shims:
        children = Path(f'/proc/{pid}/task/{pid}/children')
        if children.exists():
            for value in children.read_text().split():
                child = int(value)
                cgroup = Path(f'/proc/{child}/cgroup')
                if cgroup.exists() and identifier in cgroup.read_text():
                    os.kill(child, signal.SIGTERM)
                    wait_gone(child)
        if Path(f'/proc/{pid}').exists():
            os.kill(pid, signal.SIGTERM)
            wait_gone(pid)
    for pid in runtime_pids():
        os.kill(pid, signal.SIGTERM)
        wait_gone(pid)


def restore_applications():
    run(['systemctl', 'start', 'k3s'], timeout=180)
    run(CLI + ['wait', '--for=condition=Ready', 'node/cvtailor-prod', '--timeout=180s'])
    run(CLI + ['scale', 'deployment/cvtailor', 'deployment/cvtailor-demo', '--replicas=1'])
    for name, port in [('cvtailor', 18000), ('cvtailor-demo', 18001)]:
        run(CLI + ['rollout', 'status', 'deployment/' + name, '--timeout=180s'])
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/health', timeout=10) as response:
            assert response.status == 200


def main():
    assert os.geteuid() == 0 and os.path.ismount('/storage')
    assert SOURCE.is_dir() and not SOURCE.is_symlink()
    assert TARGET.is_dir() and not TARGET.is_symlink()
    assert not SAVED.exists() and not DROPIN.exists()
    assert len(runtime_pids()) == 1, 'Identify the running K3s runtime before maintenance'
    private = Path(Path('/var/lib/cvtailor-migration/current').read_text().strip())
    import runpy

    migration = runpy.run_path(str(Path(__file__).with_name('k8s-production.py')))
    configuration = Path('/etc/nginx/sites-enabled/cv.banas.dev.conf').resolve()
    original = configuration.read_text()
    marker = Path('/run/cvtailor-maintenance')
    assert not marker.exists() and not marker.is_symlink()
    assert 'if (-f /run/cvtailor-maintenance)' not in original
    descriptors = []
    changed = False
    started = time.time()
    with Path('/var/lib/cvtailor-cd/deploy.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        configuration.write_text(original.replace('    listen 443 ssl http2;\n',
            '    listen 443 ssl http2;\n    if (-f /run/cvtailor-maintenance) { return 503; }\n', 1))
        run(['nginx', '-t'])
        run(['systemctl', 'reload', 'nginx'])
        marker.touch(mode=0o644)
        try:
            print('Storage cutover: maintenance and drain', flush=True)
            descriptors = migration['drain']([Path('/var/lib/cvtailor/production') / mode for mode in ['main', 'demo']], timeout=600)
            run(CLI + ['scale', 'deployment/cvtailor', 'deployment/cvtailor-demo', '--replicas=0'])
            run(CLI + ['wait', '--for=delete', 'pod', '--all', '--timeout=120s'])
            stop_runtime()
            print('K3s stopped; verifying and synchronizing its image store', flush=True)
            result = run(['rsync', '-acHAXx', '--numeric-ids', '--delete', '--itemize-changes', str(SOURCE) + '/', str(TARGET) + '/'], timeout=600)
            (private / 'containerd-final-rsync.log').write_text(result.stdout)
            SOURCE.rename(SAVED)
            SOURCE.symlink_to(TARGET, target_is_directory=True)
            changed = True
            DROPIN.parent.mkdir(exist_ok=True)
            DROPIN.write_text('[Unit]\nRequiresMountsFor=/storage\nConditionPathIsMountPoint=/storage\n\n[Service]\nExecStartPre=/usr/bin/test -L /var/lib/rancher/k3s/agent/containerd\nExecStartPre=/usr/bin/test -d /storage/cvtailor-k3s-runtime/containerd\n')
            run(['systemctl', 'daemon-reload'])
            restore_applications()
            (private / 'containerd-storage-move.json').write_text(json.dumps({'source': str(SOURCE), 'target': str(TARGET),
                'maintenance_seconds': round(time.time() - started), 'completed_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'docker_moved': False, 'application_data_moved': False, 'verified_rsync_checksums': True}, indent=2))
            print('K3s healthy using its image store on storage', flush=True)
        except BaseException:
            print('Storage move failed; restoring original local K3s runtime', flush=True)
            stop_runtime()
            if changed:
                # This path is a symlink created above; never delete a runtime directory here.
                assert SOURCE.is_symlink() and SOURCE.resolve() == TARGET
                SOURCE.unlink()
                SAVED.rename(SOURCE)
                DROPIN.unlink(missing_ok=True)
                run(['systemctl', 'daemon-reload'])
            restore_applications()
            raise
        finally:
            for descriptor in descriptors:
                os.close(descriptor)
            configuration.write_text(original)
            run(['nginx', '-t'])
            run(['systemctl', 'reload', 'nginx'])
            marker.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
