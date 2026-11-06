from concurrent.futures import ThreadPoolExecutor

import pytest

from app.services.ai_provider import DailyAIBudgetExceeded
from app.services.resource_budget import ResourceBudget


def test_preflight_does_not_consume_or_write_usage(tmp_path):
    budget = ResourceBudget(tmp_path, daily_calls=2)
    before = budget.path.read_bytes()
    assert budget.remaining_ai_calls() == 2
    assert budget.check_ai_available() is None
    assert budget.remaining_ai_calls() == 2
    assert budget.path.read_bytes() == before


def test_exhaustion_does_not_charge_another_call(tmp_path):
    budget = ResourceBudget(tmp_path, daily_calls=2)
    budget.charge()
    budget.charge()
    before = budget.path.read_bytes()
    assert budget.remaining_ai_calls() == 0
    with pytest.raises(DailyAIBudgetExceeded):
        budget.check_ai_available()
    with pytest.raises(DailyAIBudgetExceeded):
        budget.charge()
    assert budget.remaining_ai_calls() == 0
    assert budget.path.read_bytes() == before


def test_concurrent_charges_share_the_atomic_sqlite_limit(tmp_path):
    budgets = [ResourceBudget(tmp_path, daily_calls=5), ResourceBudget(tmp_path, daily_calls=5)]
    def charge(index):
        try:
            budgets[index % 2].charge()
            return True
        except DailyAIBudgetExceeded:
            return False
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert sum(pool.map(charge, range(20))) == 5
    assert all(budget.remaining_ai_calls() == 0 for budget in budgets)


def test_retry_after_is_positive_and_utc_based(monkeypatch):
    monkeypatch.setattr('time.time', lambda: 86400 + 10.5)
    assert DailyAIBudgetExceeded().retry_after_seconds == 86390
    monkeypatch.setattr('time.time', lambda: 172799.9)
    assert DailyAIBudgetExceeded().retry_after_seconds == 1


def test_utc_reset_restores_capacity_without_a_preflight_write(tmp_path, monkeypatch):
    monkeypatch.setattr('time.time', lambda: 86400 + 100)
    budget = ResourceBudget(tmp_path, daily_calls=2)
    budget.charge()
    budget.charge()
    assert budget.remaining_ai_calls() == 0
    before = budget.path.read_bytes()
    monkeypatch.setattr('time.time', lambda: 172800)
    assert budget.remaining_ai_calls() == 2
    assert budget.check_ai_available() is None
    assert budget.path.read_bytes() == before
    budget.charge()
    assert budget.remaining_ai_calls() == 1


def test_accounts_have_independent_budgets(tmp_path):
    other = tmp_path / 'other'
    other.mkdir()
    first = ResourceBudget(tmp_path, daily_calls=1)
    second = ResourceBudget(other, daily_calls=1)
    first.charge()
    with pytest.raises(DailyAIBudgetExceeded):
        first.charge()
    assert second.remaining_ai_calls() == 1
    second.charge()
    assert second.remaining_ai_calls() == 0
