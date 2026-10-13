"""Exercise the real shell control flow with isolated Docker/HTTP stand-ins."""
import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REVISION = 'a' * 40
DIGEST = 'sha256:' + 'b' * 64


@pytest.fixture
def deployment(tmp_path):
    binaries = tmp_path / 'bin'
    binaries.mkdir()
    log = tmp_path / 'commands'
    state = tmp_path / 'phase'
    docker = binaries / 'docker'
    docker.write_text('''#!/usr/bin/env bash
set -eu
printf '%s\\n' "$*" >> "$TEST_LOG"
case "$1" in
  login) cat >/dev/null ;;
  pull) ;;
  exec) [[ ${TEST_CASE:-} != active ]] ;;
  image) printf '%s\\n' "${TEST_IMAGE_REVISION:-$TEST_REVISION}" ;;
  inspect)
    case "$3" in
      *State.Running*) echo true ;;
      *revision*) if [[ -f $TEST_PHASE ]]; then echo "$TEST_REVISION"; else printf '%040d\\n' 0; fi ;;
      *) echo sha256:previous ;;
    esac ;;
  compose)
    if [[ ! -f $TEST_PHASE ]]; then
      touch "$TEST_PHASE"
      [[ ${TEST_CASE:-} != compose_failure ]]
    else
      touch "$TEST_PHASE.rollback"
    fi ;;
esac
''')
    curl = binaries / 'curl'
    curl.write_text('''#!/usr/bin/env bash
if [[ ${TEST_CASE:-} == health_failure && ! -f $TEST_PHASE.rollback ]]; then exit 1; fi
''')
    sleep = binaries / 'sleep'
    sleep.write_text('#!/usr/bin/env bash\nexit 0\n')
    for binary in binaries.iterdir():
        binary.chmod(0o755)
    config = tmp_path / 'config'
    config.write_text(f'''PATH={binaries}:/usr/bin:/bin
APP_DIR={tmp_path}
COMPOSE_FILE={tmp_path}/compose.yml
STATE_DIR={tmp_path}/state
CONTAINER=cv-tailor
SERVICE=cv-tailor
IMAGE_REPOSITORY=ghcr.io/rafalbanas/ai-resume-tailoring-platform
REGISTRY_USER=rafalbanas
HEALTH_URL=http://127.0.0.1:18000/health
''')
    env = dict(os.environ, CVTAILOR_DEPLOY_CONFIG=str(config), TEST_LOG=str(log),
               TEST_PHASE=str(state), TEST_REVISION=REVISION)
    def run(case='', revision=REVISION, digest=DIGEST, **extra):
        return subprocess.run(['bash', str(ROOT/'deploy/cd/deploy.sh'), revision, digest],
            env=dict(env, TEST_CASE=case, **extra), input='ephemeral-test-token\n',
            capture_output=True, text=True)
    return run, log, tmp_path


def test_deploy_success_pins_digest_and_persists_state(deployment):
    run, log, path = deployment
    result = run()
    assert result.returncode == 0, result.stderr
    assert DIGEST in (path/'state/current.yml').read_text()
    assert (path/'state/previous-image').read_text().strip() == 'sha256:previous'
    assert 'login ghcr.io' in log.read_text()
    assert 'ephemeral-test-token' not in result.stdout + result.stderr + log.read_text()
    assert not list((path/'state').glob('override.*'))


@pytest.mark.parametrize('case', ['compose_failure', 'health_failure'])
def test_failed_release_restores_previous_image(deployment, case):
    run, log, path = deployment
    result = run(case)
    assert result.returncode != 0
    assert 'Previous image restored.' in result.stderr
    assert log.read_text().count('compose ') == 2
    assert not (path/'state/current.yml').exists()


def test_active_analyses_block_deployment(deployment):
    run, log, _ = deployment
    assert run('active').returncode != 0
    assert 'compose ' not in log.read_text()
    assert 'pull ' not in log.read_text()


def test_wrong_revision_and_invalid_arguments_do_not_restart(deployment):
    run, log, _ = deployment
    assert run(TEST_IMAGE_REVISION='c'*40).returncode != 0
    assert 'compose ' not in log.read_text()
    assert run(revision='main;touch /tmp/injection').returncode == 2


@pytest.mark.parametrize('command', ['bash', 'deploy main latest', 'deploy ' + REVISION + ' ' + DIGEST + '; id', ''])
def test_ssh_entrypoint_rejects_arbitrary_commands(command):
    result = subprocess.run(['bash', str(ROOT/'deploy/cd/ssh-command.sh')],
        env=dict(os.environ, SSH_ORIGINAL_COMMAND=command), capture_output=True, text=True)
    assert result.returncode == 2
