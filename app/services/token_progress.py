"""Task-scoped exact usage, published only when providers report final counts."""
import time
from contextlib import contextmanager
from contextvars import ContextVar
from uuid import uuid4

_listener = ContextVar('token_progress_listener', default=None)


def report(call_id, **values):
    listener = _listener.get()
    if listener:
        listener(call_id, values)


def new_call(provider, model):
    call_id = uuid4().hex
    report(call_id, provider=provider, model=model, phase='waiting')
    return call_id


@contextmanager
def track_tokens(callback):
    calls, last = {}, 0.0
    def receive(call_id, values):
        nonlocal last
        calls.setdefault(call_id, {}).update(values)
        now = time.monotonic()
        if now-last < .25 and values.get('phase') not in {'waiting', 'done'}:
            return
        last = now
        publish()
    def publish():
        finished = [c for c in calls.values() if c.get('phase') == 'done']
        active = [c for c in calls.values() if c.get('phase') != 'done']
        known = [c for c in finished if isinstance(c.get('total_tokens'), int)]
        callback({'calls': len(calls), 'completed_calls': len(finished),
                  'input_tokens': sum(c['input_tokens'] for c in finished) if all(isinstance(c.get('input_tokens'), int) for c in finished) else None,
                  'output_tokens': sum(c['output_tokens'] for c in finished) if all(isinstance(c.get('output_tokens'), int) for c in finished) else None,
                  'total_tokens': sum(c['total_tokens'] for c in known),
                  'tokens_per_second': finished[-1].get('tokens_per_second') if finished else None,
                  'active': bool(active), 'complete_usage': len(known) == len(calls),
                  'model': (active[-1] if active else finished[-1]).get('model') if calls else None})
    token = _listener.set(receive)
    try:
        yield
    finally:
        for c in calls.values():
            if c.get('phase') != 'done':
                c.update(phase='done', total_tokens=None)
        if calls:
            publish()
        _listener.reset(token)
