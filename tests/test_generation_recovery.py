"""Bounded recovery must retain source provenance and never accept partial CVs."""
import json

import httpx
import pytest

from app.models.job import JobAnalysis, JobRequest
from app.services.ollama_analysis import OllamaAnalysisError
from tests.test_ollama_token_budget import make_provider


@pytest.mark.parametrize('repair_success', [True, False])
async def test_literal_classification_conflicts_retry_only_affected_occurrences(profile, repair_success):
    job = JobRequest(company='Synthetic', role='Audit Analyst', job_description=(
        'Requirements\nExperience with Python.\nResponsibilities\n'
        'Coordinates audit reviews.\nCoordinates audit reviews.'))
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][1]['content'])
        requests.append(payload)
        duplicate = 0
        rows = []
        for p in payload['passages']:
            row = dict(p=p['id'], k='context')
            if p['text'] == 'Experience with Python.':
                row.update(k='requirement', n='Python experience', priority='mandatory', s='missing',
                           f=[], why='No matching experience confirmed.')
            elif p['text'] == 'Coordinates audit reviews.':
                duplicate += 1
                row['k'] = 'responsibility' if (len(requests) > 1 and repair_success) or duplicate == 2 else 'context'
            rows.append(row)
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': rows})}, 'done_reason': 'stop'})

    provider = make_provider(handler, ollama_analysis_recovery_calls=2)
    if repair_success:
        result = await provider.analyze_job(job, profile)
        assert result.is_reliable
        assert len(result.requirements) == 1
        assert result.requirements[0].name == 'Python experience'
        assert len(requests) == 2
    else:
        with pytest.raises(OllamaAnalysisError) as exc:
            await provider.analyze_job(job, profile)
        assert exc.value.kind == 'coverage'
        assert len(requests) == 3  # initial + the shared recovery budget, no loop
    for payload in requests[1:]:
        assert [p['text'] for p in payload['passages']] == ['Coordinates audit reviews.'] * 2
        assert payload['job_source'] == job.job_description


def analysis(job):
    return JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                       missing_requirements=[], recommendation='REVIEW', match_level='LOW')


@pytest.mark.parametrize('outcome', ['success', 'output_limit', 'invalid_json'])
async def test_truncated_cv_gets_one_concise_retry_on_same_model_and_budget(profile, outcome):
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1 or outcome == 'output_limit':
            return httpx.Response(200, json={'message': {'content': '{"headline":"unfinished'}, 'done_reason': 'length'})
        if outcome == 'invalid_json':
            return httpx.Response(200, json={'message': {'content': 'not JSON'}, 'done_reason': 'stop'})
        payload = json.loads(body['messages'][1]['content'])
        catalog = payload['source_catalog']
        summary = next(e for e in catalog if e['type'] == 'summary')
        owned = next(e for e in catalog if e['type'] == 'experience')
        history = payload['candidate_facts']['employment_history']
        resume = dict(headline='Support Engineer', professional_summary=summary['fact'],
                      summary_source_fact_ids=[summary['source_id']], selected_skill_ids=[], core_skills=[],
                      education=[], projects=[], experience=[dict(company=h['company'], title=h['title'], dates='',
                          bullets=[dict(text=owned['fact'], source_fact_ids=[owned['source_id']])]) for h in history])
        return httpx.Response(200, json={'message': {'content': json.dumps(resume)}, 'done_reason': 'stop'})

    provider = make_provider(handler)
    job = JobRequest(company='Synthetic', role='Support', job_description='Requirements\nPython support and automation.')
    if outcome == 'success':
        resume = await provider.tailor_resume(job, profile, analysis(job))
        assert len(resume.experience) == len(profile.experience)
        assert resume.professional_summary == profile.summary_facts[0]
    else:
        with pytest.raises(OllamaAnalysisError) as exc:
            await provider.tailor_resume(job, profile, analysis(job))
        assert exc.value.kind == outcome
    assert len(requests) == 2
    assert requests[0]['model'] == requests[1]['model']
    assert requests[0]['options'] == requests[1]['options']
    assert requests[0]['messages'][1] == requests[1]['messages'][1]  # full evidence retained
    props = requests[1]['format']['properties']
    assert props['professional_summary']['maxLength'] == 360
    assert props['projects']['maxItems'] <= 2
    assert props['experience']['items']['properties']['bullets']['maxItems'] == 2


@pytest.mark.parametrize('kind', ['invalid_json', 'context_budget'])
async def test_non_length_cv_failure_does_not_trigger_retry(profile, kind):
    calls = []

    async def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'message': {'content': 'not JSON'},
            'done_reason': 'length' if kind == 'context_budget' else 'stop',
            'prompt_eval_count': 32500, 'eval_count': 50})

    provider = make_provider(handler)
    job = JobRequest(company='Synthetic', role='Support', job_description='Requirements\nPython support and automation.')
    with pytest.raises(OllamaAnalysisError) as exc:
        await provider.tailor_resume(job, profile, analysis(job))
    assert exc.value.kind == kind
    assert len(calls) == 1


async def test_conflicting_title_occurrences_are_not_forced_into_qualifications(profile):
    job = JobRequest(company='Synthetic', role='Audit Analyst', job_description=(
        'Requirements\nExperience with Python.\nAbout the role\nAudit Analyst'))
    requests = []

    async def handler(request):
        body = json.loads(request.content)
        payload = json.loads(body['messages'][1]['content'])
        requests.append(body)
        titles, rows = 0, []
        for p in payload['passages']:
            row = dict(p=p['id'], k='context')
            if p['text'] == 'Experience with Python.':
                row.update(k='requirement', n='Python experience', priority='mandatory', s='missing',
                           f=[], why='No matching experience confirmed.')
            elif p['text'] == job.role:
                titles += 1
                if len(requests) == 1 and titles == 2:
                    row['k'] = 'responsibility'
            rows.append(row)
        return httpx.Response(200, json={'message': {'content': json.dumps({'rows': rows})}, 'done_reason': 'stop'})

    result = await make_provider(handler).analyze_job(job, profile)
    assert result.is_reliable
    assert len(result.requirements) == 1
    assert result.requirements[0].source_quote != job.role
    assert len(requests) == 2
    schema = requests[1]['format']
    for ref in schema['properties']['assessments']['properties'].values():
        kinds = schema['$defs'][ref['$ref'].split('/')[-1]]['properties']['k']['enum']
        assert 'context' in kinds
