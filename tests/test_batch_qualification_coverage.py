"""Fictional batch reproductions; source coverage is not semantic assessment."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import (
    AnalysisInventory,
    CompactAssessment,
    CompactInterpretation,
    assessment_priority,
    needs_assessment,
)

MANDATORY = [
    'Doskonała znajomość protokołów HTTPS, sesji i nagłówków bezpieczeństwa.',
    'Głębokie, inżynieryjne zrozumienie protokołów sieciowych i architektur enterprise.',
    'BSc or equivalent in Computer Science or a related discipline.',
    'Must have hands-on experience with scripting languages: Python/PySpark and workflow tools including MLflow.',
    'Mandatory AI proficiency, including machine learning and secure AI business processes.',
    'Strong cybersecurity expertise across architecture, identity or data protection.',
    'Wykształcenie minimum średnie',
    'English on an advanced level (min. B2)',
    'Sumienność i odpowiedzialne podejście do zadań',
    'Elastyczność i otwartość na zmiany',
    'Innowacyjne podejście do rozwiązywania problemów',
    'Analytical mindset, a natural problem solver with a hands-on approach',
    'The desire to learn new technical skills',
    'Clear written and verbal communication skills',
    'Strong leadership presence and people management capabilities',
    'Deep product knowledge, including common troubleshooting workflows',
    'Troubleshooting skills and the ability to resolve technical issues',
    'A structured approach to documentation and prioritization',
]
PREFERRED = [
    'Docenimy doświadczenie z rozwiązaniami multi-agentowymi.',
    'Dodatkowym atutem będzie znajomość SQL oraz systemu ExampleFlow.',
    'Nice to have: Terraform; Azure Automation/Functions',
]


def inventory(source):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'})
    job = JobRequest(company='Synthetic', role='Engineer', job_description='JOB DESCRIPTION\n' + source)
    return job, profile, AnalysisInventory.build(job, profile)


@pytest.mark.parametrize('quote', MANDATORY + PREFERRED)
@pytest.mark.parametrize('kind', ['context', 'responsibility', 'competency'])
def test_missing_qualification_cannot_pass_independent_final_validator(quote, kind):
    job, profile, inv = inventory('Requirements\n' + quote)
    rows = [CompactAssessment(p=pid, k=kind, n=quote, why='Not documented.')
            if passage['text'] == quote else CompactAssessment(p=pid, k='context')
            for pid, passage in inv.passages.items()]
    report = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert report.recommendation == 'RETRY'
    assert quote in report.unassessed_source_passages


@pytest.mark.parametrize('quote', MANDATORY + PREFERRED)
def test_schema_requires_assessment_with_literal_priority(quote):
    _, _, inv = inventory('Requirements\n' + quote)
    pid, passage = next((pid, p) for pid, p in inv.passages.items() if p['text'] == quote)
    assert needs_assessment(passage)
    assert assessment_priority(passage) == ('preferred' if quote in PREFERRED else 'mandatory')
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    props = schema['$defs'][ref]['properties']
    assert props['k']['enum'] == ['requirement']


@pytest.mark.parametrize('quote', PREFERRED)
@pytest.mark.parametrize('normalize_rows', [False, True])
def test_inline_preference_under_requirements_does_not_become_mandatory(quote, normalize_rows):
    job, profile, inv = inventory('Requirements\n' + quote)
    rows = [CompactAssessment(p=pid, k='requirement', n=quote, why='Not documented.', priority='mandatory')
            if p['text'] == quote else CompactAssessment(p=pid, k='context')
            for pid, p in inv.passages.items()]
    if normalize_rows:
        rows = inv.validate_rows(rows, list(inv.passages))
    report = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert report.is_reliable, report.completeness_issues
    assert report.requirements
    assert all(r.priority == 'preferred' for r in report.requirements)
    assert all(r.status == 'missing' and not r.source_fact_ids for r in report.requirements)


@pytest.mark.parametrize('quote', [
    'We offer a training budget.', 'Our company develops innovative software.',
    'Contact us: hiring@example.invalid', 'Free sports membership',
])
def test_benefits_and_administration_do_not_become_candidate_conditions(quote):
    assert not needs_assessment({'text': quote, 'hints': ['benefits']})


def test_appreciating_an_application_is_not_a_preferred_qualification():
    assert not needs_assessment({'text': 'Docenimy przesłanie aplikacji przez formularz.', 'hints': ['recruitment']})


@pytest.mark.parametrize('quote', ['Python', 'Azure Logic Apps', 'Annual learning allowance'])
def test_bare_products_and_offered_perks_do_not_bind_qualification_grammar(quote):
    assert not needs_assessment({'text': quote, 'hints': ['mandatory']})


def test_mandatory_predicate_before_colon_and_trailing_preference_are_preserved():
    from app.services.ollama_analysis import condition_text
    quote = MANDATORY[3]
    assert condition_text({'text': quote}) == quote
    assert assessment_priority({'text': 'Experience with Python, preferably Rust.', 'hints': ['mandatory']}) == 'mandatory'


def test_qualifications_inside_inherited_stack_are_not_exempt_metadata():
    quote = 'Proven experience with production AI integrations.'
    job, profile, inv = inventory('Tech Stack\nPython\nAn unfamiliar qualification heading\n' + quote)
    rows = [CompactAssessment(p=pid, k='context') for pid in inv.passages]
    report = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert quote in report.unassessed_source_passages


def test_complete_mixed_offer_and_revalidation_keep_assessments_and_priorities():
    duties = ['Design integration solutions.', 'Maintain service documentation.']
    source = ('Tech Stack\nPython\nregular\nRequirements\n' + '\n'.join(MANDATORY + PREFERRED)
              + '\nResponsibilities\n' + '\n'.join(duties) + '\nBenefits\nFree sports membership')
    job, profile, inv = inventory(source)
    rows = []
    for pid, passage in inv.passages.items():
        quote = passage['text']
        if quote in MANDATORY + PREFERRED:
            rows.append(CompactAssessment(p=pid, k='requirement', n=quote[:120], why='Not documented.',
                                          priority='preferred' if quote in PREFERRED else 'mandatory'))
        else:
            rows.append(CompactAssessment(p=pid, k='responsibility' if quote in duties else 'context'))
    report = inv.expand(inv.validate_rows(rows, list(inv.passages))).to_analysis(job)
    for _ in range(3):
        report = AnalysisValidator(profile).validate(
            report, job.role + '\n' + job.job_description, semantic=True)
        assert report.is_reliable, report.completeness_issues
        assert len(report.requirements) == len(MANDATORY + PREFERRED)
        assert sum(r.priority == 'mandatory' for r in report.requirements) == len(MANDATORY)
        assert sum(r.priority == 'preferred' for r in report.requirements) == len(PREFERRED)
        assert all(r.status == 'missing' and not r.source_fact_ids for r in report.requirements)
        assert not report.unassessed_source_passages


@pytest.mark.asyncio
async def test_bounded_recovery_requests_hidden_conditions_not_benefits():
    from app.services.indexed_analysis import indexed_interpretation
    quotes = [MANDATORY[0], MANDATORY[2], PREFERRED[0]]
    source = 'Requirements\n' + '\n'.join(quotes) + '\nBenefits\nFree sports membership'
    job, profile, inv = inventory(source)
    calls = []

    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(payload)
            return CompactInterpretation(rows=[CompactAssessment(
                p=p['id'], k='requirement', n=p['text'], why='Not documented.',
                priority='preferred' if p['text'] in PREFERRED else 'mandatory')
                if len(calls) > 1 and p['text'] in quotes else CompactAssessment(p=p['id'], k='context')
                for p in payload['passages']])

    result = await indexed_interpretation(Provider(), inv)
    assert len(calls) == 2
    assert {p['text'] for p in calls[1]['passages']} == set(quotes)
    report = AnalysisValidator(profile).validate(
        result.to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert report.is_reliable, report.completeness_issues
    assert len(report.requirements) == len(quotes)
