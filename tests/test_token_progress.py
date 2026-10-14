import asyncio
import json

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.services.ollama_analysis import OllamaAnalysisError
from app.services.ollama_provider import OllamaProvider
from app.services.token_progress import new_call, report, track_tokens


class Answer(BaseModel):
    value: int


@pytest.mark.asyncio
async def test_exact_statistics_arrive_only_after_completed_call():
    updates = []
    async def handler(request):
        assert json.loads(request.content)['stream'] is False
        assert updates[-1]['active'] and updates[-1]['completed_calls'] == 0
        assert updates[-1]['tokens_per_second'] is None
        return httpx.Response(200, json={'message': {'content': '{"value":7}'}, 'done': True, 'done_reason': 'stop', 'prompt_eval_count': 20, 'eval_count': 9, 'eval_duration': 500_000_000})
    provider = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(handler))
    with track_tokens(updates.append):
        result = await provider._chat(Answer, 'JSON only', {'stage': 'test'})
    assert result.value == 7
    final = updates[-1]
    assert final['total_tokens'] == 29 and final['output_tokens'] == 9
    assert final['tokens_per_second'] == 18
    assert final['complete_usage'] and not final['active']
    assert 'content' not in json.dumps(updates)


@pytest.mark.asyncio
async def test_failed_call_does_not_invent_usage():
    provider = OllamaProvider(Settings(_env_file=None), transport=httpx.MockTransport(lambda request: httpx.Response(503)))
    updates = []
    with track_tokens(updates.append):
        with pytest.raises(OllamaAnalysisError):
            await provider._chat(Answer, 'JSON', {})
    assert not updates[-1]['complete_usage']
    assert updates[-1]['tokens_per_second'] is None
    assert updates[-1]['total_tokens'] == 0


def test_retry_totals_and_unknown_usage_are_not_estimated_as_actual():
    updates = []
    with track_tokens(updates.append):
        for _ in range(2):
            call = new_call('ollama', 'model')
            report(call, phase='done', input_tokens=10, output_tokens=5, total_tokens=15)
        new_call('ollama', 'model')
    assert updates[-1]['calls'] == 3
    assert updates[-1]['total_tokens'] == 30
    assert not updates[-1]['complete_usage']


@pytest.mark.asyncio
async def test_concurrent_task_usage_is_isolated():
    async def run(total):
        updates = []
        with track_tokens(updates.append):
            call = new_call('ollama', 'model')
            await asyncio.sleep(0)
            report(call, phase='done', input_tokens=total, output_tokens=0, total_tokens=total)
        return updates[-1]
    a, b = await asyncio.gather(run(10), run(20))
    assert a['total_tokens'] == 10 and b['total_tokens'] == 20
    assert a['calls'] == b['calls'] == 1


def test_usage_separates_ollama_repairs_from_gemini_fallback():
    updates = []
    with track_tokens(updates.append):
        for provider, amount in [('ollama', 20), ('ollama', 10), ('gemini', 7)]:
            call = new_call(provider, 'test')
            report(call, phase='done', input_tokens=amount, output_tokens=0, total_tokens=amount)
        new_call('gemini', 'test')
    final = updates[-1]
    assert final['total_tokens'] == 37 and final['calls'] == 4
    assert final['providers'] == [
        {'provider': 'ollama', 'calls': 2, 'total_tokens': 30, 'complete_usage': True},
        {'provider': 'gemini', 'calls': 2, 'total_tokens': 7, 'complete_usage': False}]
