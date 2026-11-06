import pytest
from fastapi.testclient import TestClient

from app import processing_server
from app.services.processing import ProcessingError


@pytest.mark.parametrize('error', [ValueError('synthetic-private-error'),
                                  PermissionError(1, 'synthetic-private-error'),
                                  OSError(5, 'synthetic-private-error'),
                                  ProcessingError('synthetic-private-error', code='timeout'),
                                  ProcessingError('synthetic-private-error', code='synthetic-private-code')])
def test_processing_errors_log_only_status_metadata(monkeypatch, caplog, error):
    monkeypatch.setenv('PROCESSING_TOKEN', 'synthetic-processing-token-' * 2)
    monkeypatch.delenv('PROCESSING_CONTAINER_ISOLATED', raising=False)

    def fail(*args, **kwargs):
        raise error

    monkeypatch.setattr(processing_server, 'local_process', fail)
    with TestClient(processing_server.app) as client:
        response = client.post('/process', headers={'Authorization': 'Bearer ' + 'synthetic-processing-token-' * 2},
                               json={'operation': 'reference', 'payload': {'content': 'synthetic-private-payload'}})
    assert response.status_code == 422
    assert type(error).__name__ in caplog.text
    assert f'errno={getattr(error, "errno", None)}' in caplog.text
    if getattr(error, 'code', None) == 'timeout':
        assert 'code=timeout' in caplog.text
    assert 'synthetic-private' not in caplog.text + response.text
