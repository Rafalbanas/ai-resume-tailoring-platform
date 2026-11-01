import pytest

from app.core.config import Settings
from app.models.job import JobRequest
from app.services.gemini_provider import GeminiProvider
from app.services.ollama_analysis import CompactAssessment


@pytest.mark.asyncio
@pytest.mark.parametrize('recovers', [True, False])
async def test_semantic_recovery_is_bounded_and_preserves_failure(monkeypatch, profile, recovers):
    calls = []

    async def interpret(provider, inventory, *, validation_feedback=None):
        calls.append(list(validation_feedback or []))
        return inventory.expand([CompactAssessment(p=pid, k='context') for pid in inventory.passages])

    class Validator:
        def __init__(self, *args):
            pass

        def validate(self, analysis, *args, **kwargs):
            analysis.is_reliable = recovers and len(calls) == 2
            analysis.evidence_issues = [] if analysis.is_reliable else ['Unsupported model confirmation corrected: source condition.']
            return analysis

    monkeypatch.setattr('app.services.indexed_analysis.indexed_interpretation', interpret)
    monkeypatch.setattr('app.services.gemini_provider.AnalysisValidator', Validator)
    provider = GeminiProvider(Settings(_env_file=None, gemini_api_key='synthetic'))
    result = await provider.analyze_job(JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nKnowledge of Azure.'), profile)
    assert len(calls) == 2
    assert not calls[0]
    assert 'Unsupported model confirmation' in calls[1][0]
    assert result.is_reliable is recovers
    assert bool(result.evidence_issues) is (not recovers)
