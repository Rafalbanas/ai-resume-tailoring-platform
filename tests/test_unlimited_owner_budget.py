"""Explicit private-owner opt-out must not remove demo or admission guards."""
import asyncio
import sqlite3

import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.services.ai_provider import DailyAIBudgetExceeded
from app.services.resource_budget import ResourceBudget


def usage(budget):
    with sqlite3.connect(budget.path) as db:
        return db.execute('SELECT SUM(calls) FROM usage').fetchone()[0] or 0


def test_owner_zero_is_explicit_and_demo_stays_bounded():
    settings = Settings(_env_file=None, ai_daily_call_limit=0)
    assert settings.ai_daily_call_limit == 0
    assert settings.demo_ai_daily_call_limit == 60
    assert Settings(_env_file=None).ai_daily_call_limit == 300
    for field, value in [('demo_ai_daily_call_limit', 0), ('ai_daily_call_limit', -1),
                         ('ai_daily_call_limit', 10001)]:
        with pytest.raises(ValidationError):
            Settings(_env_file=None, **{field: value})


def test_zero_allows_calls_but_preserves_accounting_and_read_only_preflight(tmp_path):
    budget = ResourceBudget(tmp_path, daily_calls=0)
    assert budget.remaining_ai_calls() is None
    before = budget.path.read_bytes()
    assert budget.check_ai_available() is None
    assert budget.path.read_bytes() == before
    for _ in range(5):
        budget.charge()
    assert usage(budget) == 5
    assert budget.remaining_ai_calls() is None
    assert budget.check_ai_available() is None


def test_reenable_limit_uses_prior_usage_including_unlimited_calls(tmp_path):
    budget = ResourceBudget(tmp_path, daily_calls=1)
    budget.charge()
    with pytest.raises(DailyAIBudgetExceeded):
        budget.charge()
    budget.daily_calls = 0
    budget.charge()
    budget.charge()
    limited = ResourceBudget(tmp_path, daily_calls=2)
    assert usage(limited) == 3
    with pytest.raises(DailyAIBudgetExceeded):
        limited.check_ai_available()
    with pytest.raises(DailyAIBudgetExceeded):
        limited.charge()
    assert usage(limited) == 3


def test_unlimited_owner_does_not_change_other_account_budget(tmp_path):
    owner = ResourceBudget(tmp_path, daily_calls=0)
    demo_dir = tmp_path / 'demo'
    demo_dir.mkdir()
    demo = ResourceBudget(demo_dir, daily_calls=1)
    owner.charge()
    owner.charge()
    demo.charge()
    assert owner.check_ai_available() is None
    with pytest.raises(DailyAIBudgetExceeded):
        demo.charge()


def test_unlimited_mode_keeps_inference_serialized(tmp_path):
    budget = ResourceBudget(tmp_path, daily_calls=0)

    async def exercise():
        active = 0
        maximum = 0

        async def call():
            nonlocal active, maximum
            async with budget.ai_call():
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0)
                active -= 1

        await asyncio.gather(*(call() for _ in range(8)))
        return maximum

    assert asyncio.run(exercise()) == 1
    assert usage(budget) == 8


@pytest.mark.parametrize('upload', [False, True])
def test_unlimited_budget_admits_batches_without_consuming_calls(monkeypatch, upload):
    from starlette.testclient import TestClient

    from app.main import app
    from app.services.task_manager import TaskManager
    from tests.test_batch_api import headers
    from tests.test_queue_controls import login

    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        budget = app.state.resource_budget
        budget.daily_calls = 1
        budget.charge()
        budget.daily_calls = 0
        if upload:
            response = client.post('/api/v1/batches/upload',
                                   files={'file': ('jobs.txt', b'https://example.com/job')},
                                   headers=headers(client))
        else:
            response = client.post('/api/v1/batches', json={'urls': ['https://example.com/job']},
                                   headers=headers(client))
        assert response.status_code == 202
        assert usage(budget) == 1
