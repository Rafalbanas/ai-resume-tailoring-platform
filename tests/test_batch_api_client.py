"""Offline checks for the user-facing CLI; never contact a live generation service."""

import importlib.util
import json
import shutil
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock

import pytest

spec = importlib.util.spec_from_file_location('batch_api_client', Path(__file__).parents[1] / 'scripts/batch_api.py')
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)
ID = 'a' * 32


@pytest.fixture
def environment(monkeypatch, tmp_path):
    cookie = tmp_path / 'cookies'
    cookie.write_text('# Netscape HTTP Cookie File\n')
    cookie.chmod(0o600)
    monkeypatch.setenv('BASE', 'https://cv.example.test')
    monkeypatch.setenv('COOKIE_FILE', str(cookie))
    monkeypatch.setenv('CSRF', 'secret-token')
    return tmp_path


def response(status='queued', items=None):
    return {'task_id': ID, 'status': status, 'stage': 'stage', 'result': {'items': items or []}}


def test_upload_and_manifest(environment, monkeypatch):
    source = environment / 'offers with ,;" spaces.txt'
    source.write_text('https://example.com/job\n')
    manifest = environment / 'tasks.jsonl'
    run = Mock(side_effect=[
        subprocess.CompletedProcess([], 0, '{}', ''),
        subprocess.CompletedProcess([], 0, json.dumps(response()), ''),
    ])
    monkeypatch.setattr(cli.subprocess, 'run', run)
    assert cli.main(['upload', '--key-prefix', 'offers-20261108', '--manifest', str(manifest), str(source)]) == 0
    saved = json.loads(manifest.read_text())
    assert saved['task_id'] == ID
    assert saved['idempotency_key'] == 'offers-20261108-01'
    assert manifest.stat().st_mode & 0o777 == 0o600
    args = run.call_args.args[0]
    assert 'secret-token' not in str(args)
    assert run.call_args.kwargs['input'] == 'X-CSRF-Token: secret-token\n'
    assert '--location' not in args
    assert '--form-string' in args
    assert '"allow_fallback":false' in str(args)
    assert '\\"' in str(args[args.index('--form') + 1])


def test_preflight_all_files_before_post(environment, monkeypatch):
    good = environment / 'good.txt'
    good.write_text('https://example.com/job')
    request = Mock()
    monkeypatch.setattr(cli.Client, 'request', request)
    assert cli.main(['upload', '--key-prefix', 'offers-123', '--manifest', str(environment / 'tasks'),
                     str(good), str(environment / 'missing.txt')]) == 1
    request.assert_not_called()


def test_http_error_stops_without_retry(environment, monkeypatch):
    run = Mock(return_value=subprocess.CompletedProcess([], 22, '{"detail":"unauthorized"}', 'HTTP 401'))
    monkeypatch.setattr(cli.subprocess, 'run', run)
    assert cli.main(['options']) == 1
    assert run.call_count == 1


def test_watch_finishes_and_deduplicates_manifest(environment, monkeypatch):
    manifest = environment / 'tasks'
    manifest.write_text(json.dumps({'task_id': ID}) + '\n')
    request = Mock(side_effect=[response('running'), response('completed')])
    sleep = Mock()
    monkeypatch.setattr(cli.Client, 'request', request)
    monkeypatch.setattr(cli.time, 'sleep', sleep)
    assert cli.main(['watch', ID, '--manifest', str(manifest), '--interval', '30']) == 0
    assert request.call_count == 2
    sleep.assert_called_once_with(30)


@pytest.mark.parametrize('status,items', [
    ('failed', []), ('rejected', []), ('cancelled', []),
    ('completed', [{'status': 'review_required'}]),
    ('completed', [{'status': 'manual_required'}]),
    ('completed', [{'status': 'failed'}]),
])
def test_incomplete_results_exit_nonzero(environment, monkeypatch, status, items):
    monkeypatch.setattr(cli.Client, 'request', Mock(return_value=response(status, items)))
    assert cli.main(['watch', ID]) == 1


@pytest.mark.parametrize('interval', ['0', '-1', 'nan', 'inf'])
def test_invalid_interval(environment, interval):
    assert cli.main(['watch', ID, '--interval', interval]) == 1


def test_cookie_permissions(environment, monkeypatch):
    (environment / 'cookies').chmod(0o644)
    assert cli.main(['options']) == 1


def test_manifest_rejects_symlink_and_public_file(environment):
    public = environment / 'public'
    public.write_text('')
    public.chmod(0o644)
    with pytest.raises(ValueError, match='prywatnym'):
        cli.open_manifest(public)
    link = environment / 'link'
    link.symlink_to(public)
    with pytest.raises(OSError):
        cli.open_manifest(link)


def test_repeated_upload_uses_same_key_and_stops_after_error(environment, monkeypatch):
    files = [environment / f'batch-{index}.txt' for index in range(3)]
    for source in files:
        source.write_text('https://example.com/job')
    request = Mock(side_effect=[{}, response(), ValueError('HTTP 429')])
    monkeypatch.setattr(cli.Client, 'request', request)
    manifest = environment / 'tasks'
    args = ['upload', '--key-prefix', 'offers-20261108', '--manifest', str(manifest), *map(str, files)]
    assert cli.main(args) == 1
    assert len(manifest.read_text().splitlines()) == 1
    assert request.call_count == 3
    assert request.call_args_list[1].kwargs['key'] == 'offers-20261108-01'
    request.reset_mock(side_effect=True)
    request.side_effect = [{}, response(), ValueError('HTTP 429')]
    assert cli.main(args) == 1
    assert request.call_args_list[1].kwargs['key'] == 'offers-20261108-01'


def test_cancel_uses_csrf(environment, monkeypatch):
    request = Mock(return_value=response('cancelled'))
    monkeypatch.setattr(cli.Client, 'request', request)
    assert cli.main(['cancel', ID]) == 0
    request.assert_called_once_with('/' + ID + '/cancel', mutate=True)


def test_no_csrf_for_reads(environment, monkeypatch):
    monkeypatch.delenv('CSRF')
    run = Mock(return_value=subprocess.CompletedProcess([], 0, '{}', ''))
    monkeypatch.setattr(cli.subprocess, 'run', run)
    assert cli.main(['options']) == 0
    assert '--header' not in run.call_args.args[0]
    assert cli.main(['cancel', ID]) == 1


@pytest.mark.parametrize('base', ['http://example.com', 'https://user:password@example.com', 'https://example.com?x=1'])
def test_unsafe_base(environment, monkeypatch, base):
    monkeypatch.setenv('BASE', base)
    assert cli.main(['options']) == 1


@pytest.mark.skipif(not shutil.which('curl'), reason='curl not installed')
def test_real_curl_multipart_offline(environment, monkeypatch):
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{}')

        def do_POST(self):
            body = self.rfile.read(int(self.headers['Content-Length']))
            requests.append((self.path, self.headers, body))
            self.send_response(202)
            self.end_headers()
            self.wfile.write(json.dumps(response()).encode())

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setenv('BASE', f'http://127.0.0.1:{server.server_port}')
        source = environment / 'offers ,;" special.txt'
        source.write_text('https://example.com/job')
        assert cli.main(['upload', '--key-prefix', 'offers-123', '--manifest', str(environment / 'tasks'),
                         str(source)]) == 0
        path, headers, body = requests[0]
        assert path == '/api/v1/batches/upload'
        assert headers['X-CSRF-Token'] == 'secret-token'
        assert headers['Idempotency-Key'] == 'offers-123-01'
        assert b'https://example.com/job' in body
        assert b'"allow_fallback":false' in body
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
