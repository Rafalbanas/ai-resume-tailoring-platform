"""Fictional automation offer: requirements must not become duties/benefits."""
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
from app.services.source_dispositions import known_source_context

MANDATORY = [
    'You have at least 3 years of experience in process automation, system integration, or backend development',
    'You have experience building and maintaining production workflows in n8n or similar tools',
    "You're proficient in at least one of the following programming languages: Python, JavaScript, or TypeScript, and working with JSON is second nature to you",
    'You have a good understanding of REST APIs and system integration mechanisms',
    'You have hands-on experience using language model APIs, including structured outputs and tool calling',
    'You know how to build reliable solutions, with error handling, idempotency, logging, and testing',
    "You're familiar with Git, Docker, and the basics of Linux",
    'You understand the importance of GDPR and securely processing sensitive data',
    'You have a process-oriented mindset: you simplify a process before automating it',
    'You understand business needs and can evaluate the impact of automation',
    'You are self-reliant and accountable for solutions from analysis to ongoing maintenance',
    'You can communicate effectively with technical and non-technical stakeholders',
    'You take a critical approach to AI and understand the limitations of language models',
    "You're eager to share knowledge and document maintainable solutions",
]
PREFERRED = [
    'Have experience administering Jira and Confluence',
    'Are familiar with AI agent solutions and RAG architectures',
    'Have experience evaluating LLM quality and protecting systems against prompt injection',
    'Are familiar with Microsoft Graph API and integrating with Microsoft Teams',
]
DUTIES = [
    'Analyzing business requirements and translating them into automation solutions',
    'Designing and maintaining workflows in n8n',
    'Creating integrations using REST APIs',
    'Developing Python scripts and microservices',
]
COMPANY = ('What else sets us apart? Example Systems employs 400 experts. '
           'Most of us work in a hybrid model, some remotely, or on-site in a chosen location.')
BENEFITS = [
    'You can work in a hybrid model, from the office, or remotely',
    'the sports membership card,',
    'an opportunity to take part in internal and external trainings and industry events,',
    'many more',
    'You will receive discount codes for our online marketplace',
]
SOURCE = ('JOB DESCRIPTION\n' + COMPANY + '\nYour responsibilities:\n' + '\n'.join(DUTIES)
          + "\nYou're a perfect match for the role, if:\n" + '\n'.join(MANDATORY)
          + '\nIt would be an additional advantage if you:\n' + '\n'.join(PREFERRED)
          + '\nWhy is joining us worth it?\n' + BENEFITS[0]
          + '\nWe offer valuable benefits, such as:\n' + '\n'.join(BENEFITS[1:]))


def inventory():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'})
    job = JobRequest(company='Synthetic', role='Automation Engineer', job_description=SOURCE)
    return job, profile, AnalysisInventory.build(job, profile)


@pytest.mark.parametrize('text', MANDATORY + PREFERRED)
def test_explicit_english_candidate_predicates_require_assessment_without_heading(text):
    assert needs_assessment({'text': text, 'hints': ['unknown']})
    assert not known_source_context({'text': text, 'hints': ['benefits']})


@pytest.mark.parametrize('text', BENEFITS + [
    'You will develop Python integrations', 'You can enjoy a training budget',
    'You receive all the necessary equipment',
])
def test_benefits_and_future_duties_are_not_candidate_predicates(text):
    assert not needs_assessment({'text': text, 'hints': ['benefits']})


def test_inventory_grammar_binds_candidate_rows_and_priorities():
    _, _, inv = inventory()
    for text, priority in [(q, 'mandatory') for q in MANDATORY] + [(q, 'preferred') for q in PREFERRED]:
        pid = next(pid for pid, p in inv.passages.items() if p['text'] == text)
        assert assessment_priority(inv.passages[pid]) == priority
        schema = inv.keyed_schema([pid])
        definition = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
        props = schema['$defs'][definition]['properties']
        assert props['k']['enum'] == ['requirement']
        assert props['priority']['enum'] == [priority]


def test_canonical_benefits_cannot_become_missing_qualifications():
    _, _, inv = inventory()
    for text in BENEFITS + [COMPANY]:
        pid = next(pid for pid, p in inv.passages.items() if p['text'] == text)
        corrected = inv.validate_rows([CompactAssessment(
            p=pid, k='requirement', n='Incorrect candidate condition', priority='mandatory',
            s='missing', why='This is an employer offer, not a qualification.')], [pid])
        assert corrected[0].k == 'context', text


def test_final_validator_rejects_entire_qualification_section_hidden_as_duties():
    job, profile, inv = inventory()
    rows = [CompactAssessment(p=pid, k='responsibility') if p['text'] in MANDATORY
            else CompactAssessment(p=pid, k='context') for pid, p in inv.passages.items()]
    result = AnalysisValidator(profile).validate(
        inv.expand(rows).to_analysis(job), f'{job.role}\n{SOURCE}', semantic=True)
    assert not result.is_reliable
    assert set(MANDATORY + PREFERRED) <= set(result.unassessed_source_passages)
    assert not any(r.source_quote in BENEFITS + [COMPANY] for r in result.requirements)


def test_correct_dispositions_assess_14_required_and_4_preferred_not_benefits():
    job, profile, inv = inventory()
    rows = []
    for pid, passage in inv.passages.items():
        text = passage['text']
        if text in MANDATORY + PREFERRED:
            rows.append(CompactAssessment(p=pid, k='requirement', n=text[:120],
                                          priority='mandatory' if text in MANDATORY else 'preferred',
                                          s='missing', why='Not documented in the synthetic profile.'))
        else:
            rows.append(CompactAssessment(p=pid, k='responsibility' if text in DUTIES else 'context'))
    checked = inv.validate_rows(rows, list(inv.passages))
    result = AnalysisValidator(profile).validate(
        inv.expand(checked).to_analysis(job), f'{job.role}\n{SOURCE}', semantic=True)
    assert sum(r.priority == 'mandatory' for r in result.requirements) == 14
    assert sum(r.priority == 'preferred' for r in result.requirements) == 4
    assert not any(r.source_quote in BENEFITS + [COMPANY] for r in result.requirements)
    assert result.is_reliable, result.reasoning_summary


@pytest.mark.asyncio
async def test_indexed_retry_recovers_omitted_candidate_conditions():
    from app.services.indexed_analysis import indexed_interpretation
    _, _, inv = inventory()
    calls = []
    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(prompt)
            rows = []
            for p in payload['passages']:
                text = p['text']
                if text in MANDATORY + PREFERRED and len(calls) == 2:
                    rows.append(CompactAssessment(p=p['id'], k='requirement', n=text[:120],
                                                  priority='mandatory' if text in MANDATORY else 'preferred',
                                                  why='Not documented.'))
                elif text in BENEFITS + [COMPANY] and len(calls) == 1:
                    rows.append(CompactAssessment(p=p['id'], k='requirement', n='Employer benefit',
                                                  priority='mandatory', why='Incorrect model classification.'))
                else:
                    rows.append(CompactAssessment(p=p['id'], k='responsibility' if text in DUTIES else 'context'))
            return CompactInterpretation(rows=rows)
    result = await indexed_interpretation(Provider(), inv)
    assert len(calls) == 2
    assert len(result.requirements) == 18
    assert 'VALIDATION FEEDBACK' in calls[1]


@pytest.mark.parametrize('text', DUTIES)
def test_explicit_gerund_duties_cannot_become_hiring_prerequisites(text):
    from app.services.ollama_analysis import needs_responsibility
    assert needs_responsibility({'text': text, 'hints': ['responsibility']})
    assert not needs_assessment({'text': text, 'hints': ['responsibility']})


def test_real_availability_prerequisite_is_not_suppressed_as_flexible_work():
    quote = 'You must work on-site three days per week.'
    assert needs_assessment({'text': quote, 'hints': ['benefits']})
    assert not known_source_context({'text': quote, 'hints': ['benefits']})
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\n' + quote)
    profile = CandidateProfile(personal={})
    inv = AnalysisInventory.build(job, profile)
    bad = inv.expand([CompactAssessment(p=pid, k='context') for pid in inv.passages]).to_analysis(job)
    result = AnalysisValidator(profile).validate(bad, f'{job.role}\n{job.job_description}', semantic=True)
    assert not result.is_reliable
    assert quote in result.unassessed_source_passages


@pytest.mark.asyncio
async def test_persistent_omission_terminates_without_manufacturing_a_success():
    from app.services.ai_provider import ProviderResponseError
    from app.services.indexed_analysis import indexed_interpretation
    _, _, inv = inventory()
    calls = []
    class Provider:
        async def _chat(self, model, prompt, payload, **kwargs):
            calls.append(prompt)
            return CompactInterpretation(rows=[CompactAssessment(
                p=p['id'], k='responsibility' if p['text'] in DUTIES else 'context')
                for p in payload['passages']])
    with pytest.raises(ProviderResponseError, match='bounded recovery'):
        await indexed_interpretation(Provider(), inv)
    assert len(calls) == 2


@pytest.mark.parametrize('text', [MANDATORY[2], MANDATORY[8]])
def test_colon_after_candidate_predicate_does_not_erase_the_qualification(text):
    from app.services.ollama_analysis import condition_text
    assert condition_text({'text': text}) == text
    assert needs_assessment({'text': text, 'hints': ['unknown']})


def test_preferred_english_minimum_remains_preferred():
    quote = MANDATORY[0]
    assert assessment_priority({'text': quote, 'hints': ['preferred']}) == 'preferred'


def test_soft_trait_does_not_imply_employer_priority_without_qualification_section():
    quote = MANDATORY[-1]
    assert needs_assessment({'text': quote, 'hints': ['unknown']})
    assert assessment_priority({'text': quote, 'hints': ['unknown']}) is None
