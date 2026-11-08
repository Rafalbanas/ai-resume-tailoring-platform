"""Read-only deployment state; a stale metadata file is never an active lock."""
import fcntl
import json
import os
from datetime import datetime, timezone
from pathlib import Path


def deployment_status(data_dir):
    root = Path(data_dir)
    try:
        descriptor = os.open(root / '.deployment-admission.lock', os.O_RDONLY)
    except FileNotFoundError:
        return {'in_progress': False}
    except OSError:
        return {'in_progress': None}
    try:
        try:
            fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return {'in_progress': False}
        except BlockingIOError:
            pass
        result = {'in_progress': True, 'phase': 'unknown', 'started_at': None,
                  'drain_deadline_at': None, 'drain_seconds_remaining': None}
        try:
            with (root / '.deployment-status.json').open() as stream:
                meta = json.loads(stream.read(4097))
            if not isinstance(meta, dict):
                return result
            if meta.get('phase') in {'waiting_for_requests', 'waiting_for_tasks', 'rollout'}:
                result['phase'] = meta['phase']
            for name in ['started_at', 'drain_deadline_at']:
                stamp = datetime.fromisoformat(meta[name])
                if stamp.tzinfo is not None:
                    result[name] = stamp.isoformat()
            if result['drain_deadline_at'] and result['phase'] != 'rollout':
                deadline = datetime.fromisoformat(result['drain_deadline_at'])
                result['drain_seconds_remaining'] = max(0, int((deadline - datetime.now(timezone.utc)).total_seconds()))
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return result
    finally:
        os.close(descriptor)
