import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest


@pytest.fixture
def deployer_module(tmp_path):
    path = Path(__file__).resolve().parents[1] / 'deploy/k8s/production/deploy.py'
    spec = importlib.util.spec_from_file_location('pod_deployer', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.DATA = tmp_path / 'data'
    module.DATA.mkdir(parents=True, exist_ok=True)
    return module


def test_update_processors_success(deployer_module, monkeypatch):
    mock_admin = MagicMock()
    monkeypatch.setattr(deployer_module, "admin", mock_admin)
    images = {
        "cvtailor-processing-owner": "img1",
        "cvtailor-processing-demo": "img2"
    }
    deployer_module.update_processors(images)
    expected_calls = [
        call('set', 'image', 'deployment/cvtailor-processing-owner', 'processor=img1'),
        call('set', 'image', 'deployment/cvtailor-processing-demo', 'processor=img2'),
        call('rollout', 'status', 'deployment/cvtailor-processing-owner', '--timeout=240s'),
        call('rollout', 'status', 'deployment/cvtailor-processing-demo', '--timeout=240s')
    ]
    mock_admin.assert_has_calls(expected_calls)


def test_update_processors_best_effort_set_failure(deployer_module, monkeypatch):
    mock_admin = MagicMock()
    monkeypatch.setattr(deployer_module, "admin", mock_admin)
    images = {
        "cvtailor-processing-owner": "img1",
        "cvtailor-processing-demo": "img2"
    }
    def side_effect(cmd, *args, **kwargs):
        if cmd == 'set' and 'cvtailor-processing-owner' in args[1]:
            raise RuntimeError("Set owner failed")
        return None
    mock_admin.side_effect = side_effect
    with pytest.raises(RuntimeError, match="Processor recovery incomplete: cvtailor-processing-owner"):
        deployer_module.update_processors(images, best_effort=True)
    assert mock_admin.call_count == 3
    assert call('set', 'image', 'deployment/cvtailor-processing-demo', 'processor=img2') in mock_admin.call_args_list
    assert call('rollout', 'status', 'deployment/cvtailor-processing-demo', '--timeout=240s') in mock_admin.call_args_list


def test_update_processors_best_effort_rollout_failure(deployer_module, monkeypatch):
    mock_admin = MagicMock()
    monkeypatch.setattr(deployer_module, "admin", mock_admin)
    images = {
        "cvtailor-processing-owner": "img1",
        "cvtailor-processing-demo": "img2"
    }
    def side_effect(cmd, *args, **kwargs):
        if cmd == 'rollout' and 'cvtailor-processing-owner' in args[1]:
            raise RuntimeError("Rollout owner failed")
        return None
    mock_admin.side_effect = side_effect
    with pytest.raises(RuntimeError, match="Processor recovery incomplete: cvtailor-processing-owner"):
        deployer_module.update_processors(images, best_effort=True)
    assert mock_admin.call_count == 4
    assert call('set', 'image', 'deployment/cvtailor-processing-demo', 'processor=img2') in mock_admin.call_args_list
    assert call('rollout', 'status', 'deployment/cvtailor-processing-demo', '--timeout=240s') in mock_admin.call_args_list
