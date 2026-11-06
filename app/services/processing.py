"""Bounded, secret-free RPC for document processing; never deserialize pickle."""
import asyncio
import base64
import json
import logging
import os
import signal
import subprocess
import sys
import tempfile
import threading
import time
from contextvars import ContextVar
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
SLOTS = threading.BoundedSemaphore(1)
ENDPOINT = ContextVar("processing_endpoint", default=None)
BROWSER_ENDPOINT = ContextVar("processing_browser_endpoint", default=None)
DEADLINE = ContextVar("processing_deadline", default=None)
MAX_RESULT = 24 * 1024 * 1024
BROWSER_OPERATION_MAX_SECONDS = 20
logger = logging.getLogger(__name__)


class ProcessingError(ValueError):
    def __init__(self, message, *, code='processing_error'):
        super().__init__(message)
        self.code = code


def encoded(value):
    return base64.b64encode(value).decode('ascii')


def decoded(value):
    return base64.b64decode(value, validate=True)


def clean_environment():
    env = {key: value for key, value in os.environ.items()
           if key in {'PATH', 'LANG', 'LC_ALL', 'LD_LIBRARY_PATH', 'FONTCONFIG_PATH', 'PLAYWRIGHT_BROWSERS_PATH'}}
    # glibc's per-thread arenas reserve large virtual mappings. Pango starts
    # fontconfig threads; bound arenas so these fit the child's address-space cap.
    env['MALLOC_ARENA_MAX'] = '2'
    return env


def process(operation, payload, *, timeout=60):
    deadline = DEADLINE.get()
    if deadline is not None:
        timeout = min(timeout, deadline - time.monotonic())
    if timeout <= 0:
        raise ProcessingError('Document processing exceeded its deadline.')
    request = {'operation': operation, 'payload': payload, 'timeout_seconds': timeout}
    endpoint, token = ENDPOINT.get() or (os.environ.get('PROCESSING_URL', ''), os.environ.get('PROCESSING_TOKEN', ''))
    if operation == 'browser':
        browser_endpoint = BROWSER_ENDPOINT.get()
        if browser_endpoint is None:
            browser_endpoint = (os.environ.get('BROWSER_PROCESSING_URL', ''), os.environ.get('BROWSER_PROCESSING_TOKEN', ''))
        if browser_endpoint[0]:
            endpoint, token = browser_endpoint
    endpoint = endpoint.rstrip('/')
    if endpoint:
        try:
            with httpx.Client(timeout=timeout + 5, trust_env=False) as client:
                with client.stream('POST', endpoint + '/process', json=request,
                                   headers={'Authorization': 'Bearer ' + token,
                                            'Accept-Encoding': 'identity'}) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    for chunk in response.iter_raw():
                        size += len(chunk)
                        if size > MAX_RESULT:
                            raise ProcessingError('Processing result exceeds the size limit.')
                        chunks.append(chunk)
            result = json.loads(b''.join(chunks))
        except (httpx.HTTPError, ValueError) as exc:
            raise ProcessingError('Document processing is unavailable or exceeded its limits.') from exc
    else:
        if os.environ.get('CVTAILOR_RUNTIME_ROLE') == 'api':
            raise ProcessingError('The API image requires a configured remote processing service.')
        result = local_process(request, timeout=timeout)
    if not result.get('ok'):
        raise ProcessingError(result.get('error', 'Document processing failed.'))
    return result['result']


def local_process(request, *, timeout=60):
    if not SLOTS.acquire(blocking=False):
        raise ProcessingError('Document processing is busy. Try again shortly.', code='busy')
    try:
        with tempfile.TemporaryDirectory(prefix='cvtailor-processing-') as work:
            folder = Path(work)
            (folder / 'input.json').write_text(json.dumps(request), encoding='utf-8')
            env = clean_environment()
            env['PYTHONPATH'] = str(ROOT)
            env.update(HOME=work, TMPDIR=work, XDG_CACHE_HOME=work)
            child = subprocess.Popen([sys.executable, '-m', 'app.services.processing_worker', work],
                                     cwd=folder, env=env, stdin=subprocess.DEVNULL,
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired as exc:
                os.killpg(child.pid, signal.SIGKILL)
                child.wait()
                raise ProcessingError('Document processing exceeded the time limit.', code='timeout') from exc
            finally:
                # Kill descendants, including a browser left behind after a crash.
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                reap_container_children()
            output = folder / 'output.json'
            if child.returncode or not output.is_file() or output.stat().st_size > MAX_RESULT:
                # Only status metadata: native stderr may include private input.
                logger.warning('Processing child exited without a valid result (exit=%s)', child.returncode)
                raise ProcessingError('Document processing exceeded its resource limits.', code='invalid_result')
            return json.loads(output.read_text(encoding='utf-8'))
    finally:
        SLOTS.release()


CPU_QUEUE_WAIT_SECONDS = 60


async def cpu_work(request, function, *args, **kwargs):
    return await cpu_work_for_state(request.app.state, function, *args, **kwargs)


async def cpu_work_for_state(state, function, *args, **kwargs):
    from fastapi import HTTPException
    from starlette.concurrency import run_in_threadpool
    budget = state.resource_budget
    if budget.cpu_queue_slots.locked():
        raise HTTPException(429, 'Document processing queue is full. Try again shortly.')
    async with budget.cpu_queue_slots:
        try:
            async with asyncio.timeout(CPU_QUEUE_WAIT_SECONDS):
                await budget.cpu_slots.acquire()
        except TimeoutError as exc:
            raise HTTPException(429, 'Document processing is busy. Try again shortly.') from exc
        token = DEADLINE.set(time.monotonic() + 60)
        try:
            return await run_in_threadpool(function, *args, **kwargs)
        except ProcessingError as exc:
            raise HTTPException(422, str(exc)) from exc
        finally:
            DEADLINE.reset(token)
            budget.cpu_slots.release()


def _container_descendants(proc_root: Path) -> set[int]:
    """Snapshot descendants of container PID 1, not injected exec processes.

    Docker healthchecks/exec enter the namespace with a parent outside it
    (PPid 0). They and their children do not belong to the processor's tree.
    Detached native children orphaned by a parser are adopted by PID 1 and
    remain in scope even when they have left the original process group.
    """
    parents = {}
    for entry in proc_root.iterdir():
        if not entry.name.isdigit() or int(entry.name) == 1:
            continue
        try:
            # comm is parenthesized and can itself contain spaces or ')'.
            fields = (entry / 'stat').read_text().rsplit(') ', 1)[1].split()
            parents[int(entry.name)] = int(fields[1])
        except (OSError, ValueError, IndexError):
            # A process may exit between the directory listing and stat read.
            continue
    descendants = {1}
    while children := {pid for pid, parent in parents.items() if parent in descendants} - descendants:
        descendants.update(children)
    return descendants - {1}


def reap_container_children():
    # Playwright launches Chromium in its own session. In an isolated processor
    # PID namespace, PID 1 adopts detached children, including orphan browsers.
    # Infrastructure healthchecks/exec processes are not processor descendants.
    # Never enumerate/kill unrelated processes in local Python/CLI mode.
    if os.environ.get('PROCESSING_CONTAINER_ISOLATED') != '1':
        return
    if os.getpid() != 1:
        raise ProcessingError('Isolated processing must run as container PID 1.', code='pid_guard')
    for pid in _container_descendants(Path('/proc')):
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 0.5
    while time.monotonic() < deadline:
        try:
            child, _ = os.waitpid(-1, os.WNOHANG)
            if child == 0:
                time.sleep(0.005)
        except ChildProcessError:
            break
