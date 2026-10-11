"""Per-task private comparison capture; never emit candidate content to logs."""
import hashlib
import json
from contextlib import contextmanager
from contextvars import ContextVar

_capture = ContextVar('comparison_capture', default=None)


@contextmanager
def capture_comparison():
    records = []
    token = _capture.set(records)
    try:
        yield records
    finally:
        _capture.reset(token)


def record_call(provider, payload, system_prompt, schema, raw_response, metrics=None):
    records = _capture.get()
    if records is None:
        return
    def digest(value):
        return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    records.append({
        'provider': provider, 'stage': payload.get('stage'),
        'payload': payload, 'payload_sha256': digest(payload),
        'system_prompt_sha256': digest(system_prompt), 'schema_sha256': digest(schema),
        'raw_response': raw_response, 'metrics': metrics or {},
    })
