import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment
from app.services.source_dispositions import explicit_skill_condition


@pytest.mark.parametrize('quote', [
    'Strong Python skills for data processing.',
    'Good SQL skills.',
    'Strong written communication skills.',
    'Drive and a proactive approach: you take initiative and push things forward.',
    'Podstawowa umiejętność administrowania środowiskami Windows Server.',
])
def test_explicit_skills_cannot_be_hidden_as_duties_under_unfamiliar_headings(quote):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'})
    job = JobRequest(company='Synthetic', role='Data Engineer', job_description='What makes you successful:\n' + quote)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, passage in inv.passages.items() if passage['text'] == quote)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['k']['enum'] == ['requirement']
    rows = [CompactAssessment(p=p, k='responsibility' if p == pid else 'context') for p in inv.passages]
    report = AnalysisValidator(profile).validate(inv.expand(rows).to_analysis(job), job.role + '\n' + job.job_description, semantic=True)
    assert not report.is_reliable
    assert quote in report.unassessed_source_passages


@pytest.mark.parametrize('quote', ['Python', 'SQL', 'Good SQL systems require monitoring skills.',
                                  'Strong teams provide communication skills training.'])
def test_bare_tags_and_company_action_sentences_are_not_skill_predicates(quote):
    assert not explicit_skill_condition(quote)
