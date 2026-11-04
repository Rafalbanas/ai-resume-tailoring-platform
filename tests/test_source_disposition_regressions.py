"""Repeated portal prose cannot hide qualifications or score recruiter metadata."""
import json

import httpx
import pytest

from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.indexed_analysis import indexed_interpretation
from app.services.ollama_analysis import (
    AnalysisInventory,
    CompactAssessment,
    CompactComponent,
    CompactInterpretation,
    OllamaAnalysisError,
    needs_assessment,
)
from app.services.semantic_requirements import merge_equivalent_source_rows
from app.services.source_dispositions import known_source_context
from tests.test_ollama_token_budget import make_provider

TENURE = 'Masz doświadczenie w programowaniu w Pythonie, minimum 5 lat doświadczenia w software engineering.'
QUALIFICATIONS = {
    TENURE: 'Python software engineering experience',
    'Posiadasz praktyczne doświadczenie w tworzeniu aplikacji.': 'Application development experience',
    'Znasz architektury danych.': 'Data architectures',
}
PREFERRED = 'Znajomość języka niemieckiego.'
ADMIN = ['Nasz proces rekrutacji', 'Rozmowa z naszym rekruterem i spotkanie z zespołem.',
         'Potrzebujesz więcej informacji?', 'Skontaktuj się z nami: hiring@example.invalid',
         'Skontaktujemy się tylko z wybranymi kandydatami.', 'Co oferujemy', 'Szkolenia techniczne i certyfikaty.']
SOURCE = ('REQUIREMENTS\n' + '\n'.join(QUALIFICATIONS) + '\n' + TENURE
          + '\nMile widziane:\n' + PREFERRED + '\nZadania, które na Ciebie czekają:\n'
          'Projektowanie aplikacji.\n' + '\n'.join(ADMIN))


def inventory(profile):
    job = JobRequest(company='Synthetic', role='Software Engineer', job_description=SOURCE)
    return job, AnalysisInventory.build(job, profile)


@pytest.mark.parametrize('text', [*QUALIFICATIONS, 'Masz doświadczenie w tworzeniu API REST.',
    'Pracujesz z SQL i danymi ustrukturyzowanymi.', 'Posługujesz się językiem angielskim na poziomie minimum B2.'])
def test_explicit_polish_candidate_predicates_require_assessment(text):
    assert needs_assessment({'text': text, 'hints': []})
    assert not known_source_context({'text': text, 'hints': ['benefits']})


def test_embedded_minimum_has_required_grammar_and_original_years(profile):
    _, inv = inventory(profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == TENURE)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    props = schema['$defs'][ref]['properties']
    assert props['k']['enum'] == ['requirement']
    assert props['priority']['enum'] == ['mandatory']
    assert props['yrs'] == {'type': 'number', 'enum': [5.0]}


@pytest.mark.parametrize('text', ['Mamy 5 lat doświadczenia na rynku.', 'Pracujemy z SQL i danymi.',
    'Masz do dyspozycji budżet szkoleniowy.', 'Projektowanie aplikacji AI.', 'Szkolenia i certyfikaty.'])
def test_company_benefits_and_duties_are_not_candidate_predicates(text):
    assert not needs_assessment({'text': text, 'hints': []})


@pytest.mark.parametrize('text', ['Skontaktuj się ze mną: hiring@example.invalid',
                                'Skontaktuj się z rekruterem: hiring@example.invalid', 'hiring@example.invalid'])
def test_standalone_contact_instructions_are_not_qualifications(text):
    assert known_source_context({'text': text, 'hints': []})


def test_preferred_minimum_does_not_become_a_mandatory_blocker(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Mile widziane:\n' + TENURE)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == TENURE)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['priority']['enum'] == ['preferred']


def test_different_source_scope_and_levels_are_not_deduplicated(profile):
    _, inv = inventory(profile)
    # Literal duplicates with distinct source dispositions remain separate.
    inv.passages = {
        'P1': {'text': TENURE, 'hints': ['mandatory'], 'section': 'Requirements'},
        'P2': {'text': TENURE, 'hints': ['preferred'], 'section': 'Preferred'},
        'P3': {'text': 'Knowledge of English B2', 'hints': ['mandatory']},
        'P4': {'text': 'Knowledge of English C1', 'hints': ['mandatory']},
    }
    assert inv.unique_assessment_ids(list(inv.passages)) == list(inv.passages)


def test_actual_source_occurrences_keep_distinct_priorities(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\n' + TENURE + '\nMile widziane:\n' + TENURE))
    inv = AnalysisInventory.build(job, profile)
    pids = [pid for pid, p in inv.passages.items() if p['text'] == TENURE]
    assert [inv.passages[pid]['hints'] for pid in pids] == [['mandatory'], ['preferred']]
    assert inv.unique_assessment_ids(pids) == pids


def test_copied_conditions_under_equivalent_qualification_headings_are_assessed_once(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\n' + TENURE + '\nSprawdzisz się w tej roli, jeżeli:\n' + TENURE))
    inv = AnalysisInventory.build(job, profile)
    pids = [pid for pid, p in inv.passages.items() if p['text'] == TENURE]
    assert len(pids) == 2  # original occurrences are still auditable
    assert inv.unique_assessment_ids(pids) == pids[:1]


def test_explicit_duty_cannot_be_scored_as_a_preferred_qualification(profile):
    job = JobRequest(company='Synthetic', role='Engineer', job_description=(
        'Requirements\nKnowledge of Linux\nZadania, które na Ciebie czekają:\nProjektowanie aplikacji.'))
    inv = AnalysisInventory.build(job, profile)
    rows = [CompactAssessment(p=pid, k='requirement', n='Application design' if p['text'].startswith('Projektowanie') else 'Linux',
                              priority='preferred', why='Not documented.')
            if p['text'].startswith(('Projektowanie', 'Knowledge')) else CompactAssessment(p=pid, k='context')
            for pid, p in inv.passages.items()]
    result = AnalysisValidator(profile).validate(inv.expand(rows).to_analysis(job), f'{job.role}\n{job.job_description}', semantic=True)
    assert not result.is_reliable
    assert 'Projektowanie aplikacji.' in result.unassessed_source_passages


@pytest.mark.parametrize('kind', ['context', 'responsibility', 'competency'])
def test_final_validator_rejects_minimum_hidden_from_qualification_scoring(profile, kind):
    job, inv = inventory(profile)
    rows = [CompactAssessment(p=pid, k=kind, n='Python experience', why='Not documented.')
            if p['text'] == TENURE else CompactAssessment(p=pid, k='context') for pid, p in inv.passages.items()]
    candidate = inv.expand(rows).to_analysis(job)  # deliberately bypass input guards
    result = AnalysisValidator(profile).validate(candidate, f'{job.role}\n{SOURCE}', semantic=True)
    assert not result.is_reliable
    assert result.recommendation.value == 'RETRY'
    assert TENURE in result.unassessed_source_passages


def test_known_administration_cannot_score_even_in_a_complete_model_map(profile):
    job, inv = inventory(profile)
    rows = []
    for pid, passage in inv.passages.items():
        text = passage['text']
        if text in QUALIFICATIONS or text == PREFERRED:
            rows.append(CompactAssessment(p=pid, k='requirement', n=QUALIFICATIONS.get(text, 'German language'),
                                          why='Not documented.', priority='preferred'))
        elif text in ADMIN:
            rows.append(CompactAssessment(p=pid, k='requirement', n='Recruitment detail', why='A model mistake.',
                                          priority='preferred', s='strong'))
        elif text == 'Projektowanie aplikacji.':
            rows.append(CompactAssessment(p=pid, k='responsibility'))
        else:
            rows.append(CompactAssessment(p=pid, k='context'))
    # Independent export/admission validator must guard old/provider output too,
    # not rely only on newly constrained keyed schemas or validate_rows.
    result = AnalysisValidator(profile).validate(inv.expand(rows).to_analysis(job), f'{job.role}\n{SOURCE}', semantic=True)
    assert result.is_reliable, result.completeness_issues
    assert result.requirement_counts['mandatory'] == 3
    assert len(result.requirements) == 4
    assert not any(r.source_quote in ADMIN for r in result.requirements)
    assert all(any(p['source_quote'] == text for p in result.source_context) for text in ADMIN)
    tenure = next(r for r in result.requirements if r.source_quote == TENURE)
    assert tenure.required_years == 5
    assert tenure.status.value != 'strong'
    for _ in range(3):
        result = AnalysisValidator(profile).validate(result, f'{job.role}\n{SOURCE}')
        assert result.is_reliable
        assert len(result.requirements) == 4
        assert result.scoring_counts['mandatory_groups'] == 3


@pytest.mark.parametrize('portable', [False, True])
async def test_model_contract_repairs_conditions_and_ignores_admin_without_reassessing_copies(profile, portable):
    job, inv = inventory(profile)
    calls = []

    def response(payload):
        calls.append(payload)
        rows = []
        for passage in payload['passages']:
            pid, text = passage['id'], passage['text']
            if text == TENURE and len(calls) == 1:
                rows.append(CompactAssessment(p=pid, k='responsibility'))
            elif text in QUALIFICATIONS or text == PREFERRED:
                rows.append(CompactAssessment(p=pid, k='requirement', n=QUALIFICATIONS.get(text, 'German language'),
                                              why='Not documented.', priority='preferred'))
            elif text in ADMIN:
                rows.append(CompactAssessment(p=pid, k='requirement', n='Recruitment detail', why='Model error.', s='strong'))
            elif text == 'Projektowanie aplikacji.':
                rows.append(CompactAssessment(p=pid, k='responsibility'))
            else:
                rows.append(CompactAssessment(p=pid, k='context'))
        return CompactInterpretation(rows=rows)

    if portable:
        class Provider:
            async def _chat(self, model, prompt, payload, **kwargs):
                return response(payload)
        interpretation = await indexed_interpretation(Provider(), inv)
        result = AnalysisValidator(profile).validate(interpretation.to_analysis(job), f'{job.role}\n{SOURCE}', semantic=True)
    else:
        async def handler(request):
            body = json.loads(request.content)
            answer = response(json.loads(body['messages'][1]['content']))
            return httpx.Response(200, json={'message': {'content': answer.model_dump_json()}, 'done_reason': 'stop'})
        result = await make_provider(handler).analyze_job(job, profile)
    assert result.is_reliable
    assert result.requirement_counts['mandatory'] == 3
    assert result.scoring_counts['mandatory_groups'] == 3
    assert len(result.requirements) == 4
    assert len(calls) == 2
    assert sum(p['text'] == TENURE for p in calls[0]['passages']) == 1
    assert calls[0]['job_source'].count(TENURE) == 2
    assert [p['text'] for p in calls[1]['passages']] == [TENURE]
    assert all(payload['job_source'] == SOURCE for payload in calls)


def test_duplicate_priority_label_is_not_a_proficiency_distinction():
    quote = 'Knowledge of MCP or A2A protocols.'
    rows = [JobRequirement(name='MCP or A2A protocols', source_quote=quote, priority='preferred',
                           required_level=level) for level in ['optional', '']]
    assert len(merge_equivalent_source_rows(rows)) == 1
    levels = [JobRequirement(name='English', source_quote='English B2 and German C1', required_level=level)
              for level in ['B2', 'C1']]
    assert len(merge_equivalent_source_rows(levels)) == 2
    children = [JobRequirement(name=name, source_quote='API integration and API debugging')
                for name in ['API integration', 'API debugging']]
    assert len(merge_equivalent_source_rows(children)) == 2


def test_portable_duplicate_labels_for_one_passage_must_use_components(profile):
    _, inv = inventory(profile)
    pid = next(pid for pid, p in inv.passages.items() if p['text'] == TENURE)
    rows = [CompactAssessment(p=pid, k='requirement', n=label, why='Not documented.')
            for label in ['Python engineering', 'Backend engineering']]
    with pytest.raises(OllamaAnalysisError, match='one compound assessment') as caught:
        inv.validate_rows(rows, [pid])
    assert caught.value.kind == 'schema'
    compound = rows[0].model_copy(deep=True)
    compound.op = 'all'
    compound.c = [CompactComponent(n=label, s='missing', f=[]) for label in ['Python engineering', 'Backend engineering']]
    assert len(inv.validate_rows([compound], [pid])[0].c) == 2
