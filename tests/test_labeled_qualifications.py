"""A presentation label must not hide candidate conditions from semantic guards."""
import pytest

from app.models.job import JobAnalysis, JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import (
    AnalysisInventory,
    assessment_priority,
    needs_assessment,
    objective_condition,
)
from tests.test_airhelp_sections import BENEFITS, CLOSING, DUTIES, QUALIFICATIONS, offer


@pytest.mark.parametrize('qualification', QUALIFICATIONS)
def test_labeled_qualifications_require_mandatory_assessment(qualification, profile):
    job = JobRequest(company='Example', role='Support', job_description=offer())
    inventory = AnalysisInventory.build(job, profile)
    passage = next(p for p in inventory.passages.values() if p['text'] == qualification)
    assert needs_assessment(passage)
    assert assessment_priority(passage) == 'mandatory'


@pytest.mark.parametrize('text', [
    'Relevant Background: 1+ years of experience in first-line IT Support.',
    'Communication Skills: fluent written and spoken English (B2/C1+).',
])
def test_labeled_objective_conditions_do_not_depend_on_section_hints(text):
    passage = {'text': text, 'hints': []}
    assert objective_condition(passage)
    assert needs_assessment(passage)
    assert assessment_priority(passage) == 'mandatory'


def test_labeled_duties_and_benefits_remain_outside_qualification_scoring(profile):
    job = JobRequest(company='Example', role='Support', job_description=offer())
    inventory = AnalysisInventory.build(job, profile)
    for text in DUTIES + BENEFITS + CLOSING:
        passage = next(p for p in inventory.passages.values() if p['text'] == text)
        assert not needs_assessment(passage), text
        assert assessment_priority(passage) is None


@pytest.mark.parametrize('disposition', ['responsibility', 'context'])
def test_complete_but_incorrect_model_map_is_not_trusted(profile, disposition):
    text = offer()
    duties = DUTIES + (QUALIFICATIONS if disposition == 'responsibility' else [])
    context = [line for line in text.splitlines() if line.strip() and line not in duties]
    candidate = JobAnalysis(
        company='Example', role='Support', strong_matches=[], partial_matches=[], missing_requirements=[],
        recommendation='SKIP', match_level='LOW', analysis_method='llm_validated',
        responsibilities=[{'source_quote': quote, 'text': quote} for quote in duties],
        source_context=[{'source_quote': quote, 'text': quote} for quote in context],
    )
    checked = AnalysisValidator(profile).validate(candidate, text, semantic=True)
    assert not checked.is_reliable
    assert checked.match_level == 'UNRELIABLE'
    assert checked.recommendation == 'RETRY'
    assert set(QUALIFICATIONS) <= set(checked.unassessed_source_passages)
    assert sum(issue.startswith('Candidate condition was classified as context:')
               for issue in checked.completeness_issues) == 6
