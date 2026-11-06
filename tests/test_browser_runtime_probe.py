import pytest

from app.services import processing
from scripts.check_runtime_image import browser_rpc_check


def test_probe_uses_existing_worker_budget_without_changing_url_limits(monkeypatch):
    def rejected(operation, payload, *, timeout):
        assert operation == 'browser'
        assert payload == {'url': 'http://127.0.0.1/private', 'timeout': 2,
                           'max_bytes': 10000, 'max_redirects': 1}
        assert timeout == processing.BROWSER_OPERATION_MAX_SECONDS == 20
        raise processing.ProcessingError('Document is invalid or exceeds processing limits.')
    monkeypatch.setattr(processing, 'process', rejected)
    browser_rpc_check()


@pytest.mark.parametrize('message', [None, 'Document processing is unavailable or exceeded its limits.',
                                   'Document processing exceeded the time limit.'])
def test_probe_never_accepts_timeout_unavailability_or_private_url_success(monkeypatch, message):
    def invalid(*args, **kwargs):
        if message:
            raise processing.ProcessingError(message)
        return {'html': 'Unexpected private response'}
    monkeypatch.setattr(processing, 'process', invalid)
    with pytest.raises(AssertionError):
        browser_rpc_check()
