import json

import pytest

from app.models.job import JobRequest
from app.services.ai_provider import ProviderResponseError
from app.services.gemini_provider import to_gemini_schema
from app.services.indexed_analysis import indexed_interpretation, interpretation_payload, reference_schema
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, CompactInterpretation


def inventory(profile):
    return AnalysisInventory.build(JobRequest(company='Synthetic', role='Engineer', job_description='Unfamiliar section\nExperience with PhotonStack.\nAnnual learning allowance.'), profile)


def test_payload_carries_full_source_and_no_inherited_categories(profile):
    inv = inventory(profile)
    payload = interpretation_payload(inv, list(inv.passages))
    assert payload['job_source'].startswith('Unfamiliar section')
    assert all(set(p) == {'id', 'text'} for p in payload['passages'])
    schema = to_gemini_schema(reference_schema(inv, list(inv.passages)))
    assert '$ref' not in json.dumps(schema)
    assert schema['properties']['rows']['items']['properties']['p']['enum'] == list(inv.passages)


@pytest.mark.asyncio
async def test_targeted_recovery_keeps_completed_passages(profile):
    inv = inventory(profile)
    target = next(pid for pid, p in inv.passages.items() if p['text'].startswith('Experience'))
    calls = []

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append([p['id'] for p in payload['passages']])
            rows = []
            for p in payload['passages']:
                if p['id'] == target and len(calls) == 1:
                    continue
                rows.append(CompactAssessment(p=p['id'], k='requirement', n='PhotonStack practice', priority='mandatory', why='Not documented.')
                            if p['id'] == target else CompactAssessment(p=p['id'], k='context'))
            return CompactInterpretation(rows=rows)

    result = await indexed_interpretation(Provider(), inv)
    assert calls[1] == [target]
    assert len(result.requirements) == 1
    assert len(result.source_context) == len(inv.passages) - 1


@pytest.mark.asyncio
async def test_unassessed_condition_cannot_be_hidden_as_context(profile):
    inv = inventory(profile)

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            return CompactInterpretation(rows=[CompactAssessment(p=p['id'], k='context') for p in payload['passages']])

    with pytest.raises(ProviderResponseError, match='unassessed'):
        await indexed_interpretation(Provider(), inv)


@pytest.mark.asyncio
@pytest.mark.parametrize('field', ['n', 'why'])
async def test_retry_on_ollama_analysis_error(profile, field):
    inv = inventory(profile)
    calls = []
    target = next(pid for pid, p in inv.passages.items() if p['text'].startswith('Experience'))

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(prompt)
            assert 'keyed assessments' not in prompt
            assert '"assessments"' not in prompt
            rows = [CompactAssessment(p=pid, k='requirement', n='PhotonStack', why='Not documented.')
                    if pid == target else CompactAssessment(p=pid, k='context') for pid in inv.passages]
            if len(calls) == 1:
                setattr(next(row for row in rows if row.p == target), field, '   ')
            return CompactInterpretation(rows=rows)

    result = await indexed_interpretation(Provider(), inv)
    assert len(calls) == 2
    assert 'VALIDATION FEEDBACK' in calls[1]
    assert target in calls[1]
    assert len(result.requirements) == 1


@pytest.mark.asyncio
async def test_fail_after_two_attempts_for_stably_invalid(profile):
    inv = inventory(profile)
    calls = []

    class Provider:
        name = 'gemini'

        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(prompt)
            return CompactInterpretation(rows=[
                CompactAssessment(p=list(inv.passages)[0], k='requirement', n='', why='')
            ])

    with pytest.raises(ProviderResponseError, match='gemini.*non-blank') as caught:
        await indexed_interpretation(Provider(), inv)
    assert 'Ollama' not in str(caught.value)
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_retry_on_provider_response_error(profile):
    inv = inventory(profile)
    calls = 0

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise ProviderResponseError("Invalid structured JSON")
            return CompactInterpretation(rows=[
                CompactAssessment(p=p['id'], k='requirement', n='PhotonStack', why='Not documented.')
                if p['text'].startswith('Experience') else CompactAssessment(p=p['id'], k='context')
                for p in payload['passages']
            ])

    result = await indexed_interpretation(Provider(), inv)
    assert calls == 2
    assert len(result.requirements) == 1


@pytest.mark.asyncio
async def test_coverage_errors_are_not_retried_as_schema_errors(profile):
    from app.services.ollama_analysis import OllamaAnalysisError
    inv = inventory(profile)
    calls = []

    class Provider:
        async def _chat(self, *args, **kwargs):
            calls.append(1)
            raise OllamaAnalysisError('coverage', 'Conflicting assessments')

    with pytest.raises(OllamaAnalysisError, match='Conflicting'):
        await indexed_interpretation(Provider(), inv)
    assert len(calls) == 1
