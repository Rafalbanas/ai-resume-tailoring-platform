#!/usr/bin/env python3
"""Batch API client using an existing curl cookie jar; no third-party Python dependencies."""

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_OPTIONS = {
    'llm_provider': 'ollama', 'ollama_model': 'gemma4:12b-it-q4_K_M',
    'ollama_context': 65536, 'template_name': 'modern_sidebar',
    'export': True, 'allow_fallback': False,
}
TERMINAL = {'completed', 'failed', 'rejected', 'cancelled'}
BAD_ITEMS = {'manual_required', 'review_required', 'failed', 'cancelled'}


def task_id(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError(f'Nieprawidłowy task_id: {value!r}')
    return value


class Client:
    def __init__(self):
        self.base = os.environ.get('BASE', '').rstrip('/')
        parsed = urlsplit(self.base)
        if (not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment
                or (parsed.scheme != 'https' and not (
                    parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1', '::1'}))):
            raise ValueError('Ustaw BASE: HTTPS (HTTP tylko localhost).')
        cookie = os.environ.get('COOKIE_FILE', '')
        if not cookie or not Path(cookie).is_file():
            raise ValueError('Ustaw COOKIE_FILE na istniejący plik cookies po zalogowaniu.')
        if stat.S_IMODE(Path(cookie).stat().st_mode) & 0o077:
            raise ValueError('Plik cookies musi być prywatny: chmod 600 "$COOKIE_FILE".')
        self.cookie = cookie

    def request(self, path, *, mutate=False, fields=None, key=None):
        args = ['curl', '--fail-with-body', '-sS', '--connect-timeout', '15', '--max-time', '120',
                '--cookie', self.cookie]
        # Pass CSRF through stdin, not the process command line. Never follow redirects
        # with session credentials; a login redirect is not a successful API response.
        headers = ''
        if mutate:
            csrf = os.environ.get('CSRF', '')
            if not csrf or '\n' in csrf or '\r' in csrf:
                raise ValueError('Ustaw CSRF z tego samego logowania co COOKIE_FILE.')
            args += ['--request', 'POST', '--header', '@-']
            headers = f'X-CSRF-Token: {csrf}\n'
        if key:
            args += ['--header', f'Idempotency-Key: {key}']
        for name, value in (fields or []):
            args += ['--form' if name == 'file' else '--form-string', f'{name}={value}']
        args += [self.base + '/api/v1/batches' + path]
        result = subprocess.run(args, input=headers, capture_output=True, text=True, check=False)
        if result.returncode:
            raise ValueError(f'Błąd curl ({result.returncode}): {result.stderr.strip()}\n{result.stdout.strip()}')
        try:
            data = json.loads(result.stdout)
        except ValueError as exc:
            raise ValueError('API nie zwróciło JSON. Sprawdź BASE i logowanie.') from exc
        if not isinstance(data, dict):
            raise ValueError('Nieprawidłowa odpowiedź API (oczekiwano obiektu).')
        return data


def failed(data):
    return data.get('status') in {'failed', 'rejected', 'cancelled'} or any(
        item.get('status') in BAD_ITEMS for item in (data.get('result') or {}).get('items', [])
    )


def show(data):
    print(f"=== {data['task_id']} ===\nStatus: {data.get('status')}\nEtap: {data.get('stage')}", flush=True)
    if data.get('error'):
        print('Błąd:', data['error'])
    for item in (data.get('result') or {}).get('items', []):
        print(' -', item.get('status'), item.get('url'))
        for field in ('error', 'analysis_url', 'preview_url', 'pdf_url', 'docx_url'):
            if item.get(field):
                print(f'   {field}: {item[field]}')


def open_manifest(path):
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    if not stat.S_ISREG(os.fstat(fd).st_mode) or stat.S_IMODE(os.fstat(fd).st_mode) & 0o077:
        os.close(fd)
        raise ValueError('Manifest musi być zwykłym prywatnym plikiem (chmod 600).')
    return os.fdopen(fd, 'a', encoding='utf-8')


def upload(client, args):
    options = DEFAULT_OPTIONS
    if args.options_file:
        options = json.loads(Path(args.options_file).read_text(encoding='utf-8'))
    if not isinstance(options, dict) or 'urls' in options:
        raise ValueError('Opcje muszą być obiektem JSON bez pola urls.')
    encoded_options = json.dumps(options, separators=(',', ':'))
    if len(encoded_options) > 4096:
        raise ValueError('Opcje przekraczają 4096 znaków.')
    # Preflight every local input before submitting any work.
    inputs = []
    for index, filename in enumerate(args.files, 1):
        key = f'{args.key_prefix}-{index:02d}'
        if not re.fullmatch(r'[A-Za-z0-9._:-]{8,128}', key):
            raise ValueError('Klucz prefix-NN musi mieć 8–128 znaków: litery/cyfry/._:-')
        path = Path(filename).resolve(strict=True)
        if not path.is_file() or path.stat().st_size > 65536:
            raise ValueError(f'Nieprawidłowy plik lub rozmiar >64 KiB: {filename}')
        content = path.read_text(encoding='utf-8-sig')
        if not 1 <= len(content.split()) <= 50:
            raise ValueError(f'Plik musi zawierać 1–50 URL: {filename}')
        if any(char in str(path) for char in ('\r', '\n')):
            raise ValueError('Nazwa pliku zawiera znak nowej linii.')
        inputs.append((filename, path, key))
    with open_manifest(args.manifest) as manifest:
        client.request('/options')  # Verify session before the first POST.
        for filename, path, key in inputs:
            print(f'Wysyłam: {filename} (klucz {key})', file=sys.stderr)
            # Quote curl's multipart filename syntax, including commas/semicolons.
            escaped = str(path).replace('\\', '\\\\').replace('"', '\\"')
            data = client.request('/upload', mutate=True, key=key, fields=[
                ('file', f'@"{escaped}";type=text/plain'), ('options', encoded_options),
            ])
            task_id(data.get('task_id', ''))
            manifest.write(json.dumps({**data, 'file': filename, 'idempotency_key': key}) + '\n')
            manifest.flush()
            os.fsync(manifest.fileno())
            print(json.dumps(data), flush=True)
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('options')
    send = commands.add_parser('upload')
    send.add_argument('--key-prefix', required=True)
    send.add_argument('--manifest', required=True)
    send.add_argument('--options-file')
    send.add_argument('files', nargs='+')
    for name in ('status', 'watch'):
        command = commands.add_parser(name)
        command.add_argument('ids', nargs='*')
        command.add_argument('--manifest')
        if name == 'watch':
            command.add_argument('--interval', type=float, default=30)
    cancel = commands.add_parser('cancel')
    cancel.add_argument('id')
    args = parser.parse_args(argv)
    try:
        client = Client()
        if args.command == 'options':
            print(json.dumps(client.request('/options'), indent=2, ensure_ascii=False))
            return 0
        if args.command == 'upload':
            return upload(client, args)
        if args.command == 'cancel':
            show(client.request('/' + task_id(args.id) + '/cancel', mutate=True))
            return 0
        ids = list(args.ids)
        if args.manifest:
            for line in Path(args.manifest).read_text(encoding='utf-8').splitlines():
                if line.strip():
                    ids.append(json.loads(line)['task_id'])
        ids = list(dict.fromkeys(task_id(value) for value in ids))
        if not ids:
            raise ValueError('Podaj task_id lub --manifest.')
        if args.command == 'watch' and (not math.isfinite(args.interval) or args.interval < 3):
            raise ValueError('--interval musi być skończoną liczbą >= 3 sekund.')
        while True:
            states = [client.request('/' + value) for value in ids]
            for data in states:
                show(data)
            if args.command == 'status' or all(data.get('status') in TERMINAL for data in states):
                return int(any(failed(data) for data in states))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print('\nPrzerwano lokalny monitor. Zadania na serwerze nadal działają.', file=sys.stderr)
        return 130
    except (OSError, ValueError, KeyError) as exc:
        print(f'Błąd: {exc}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
