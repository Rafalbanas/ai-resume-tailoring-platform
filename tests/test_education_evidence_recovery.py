import pytest

from app.models.candidate import CandidateProfile, Education
from app.models.job import JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.semantic_requirements import _facts


def assess(qualification='MSc in Computer Science', dates='2022', facts=None,
           quote='Degree in IT/Computer Science or equivalent experience.'):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, education=[Education(
        institution='Synthetic University', qualification=qualification, dates=dates, facts=facts or [])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='CS degree', source_quote=quote, status='missing', reason='Model incorrectly says ongoing.')
    _facts(validator, req)
    return req


def test_completed_degree_recovers_missing_model_assessment():
    req = assess()
    assert req.status == 'strong'
    assert req.source_fact_ids and all(i.startswith('education:') for i in req.source_fact_ids)
    assert 'ongoing' not in req.reason


@pytest.mark.parametrize('kwargs', [
    {'dates': '2022 - ongoing'}, {'dates': '2099'},
    {'facts': ['Degree in progress; thesis not completed.']},
    {'qualification': 'Computer Science coursework'},
    {'qualification': 'BSc in Computer Science', 'quote': "Master's degree in Computer Science."},
    {'quote': 'Doctoral degree in Computer Science.'},
    {'quote': 'Degree in Computer Science with a cybersecurity specialisation.'},
    {'quote': 'Degree in Computer Science and five years of experience.'},
])
def test_pending_or_stronger_scope_is_not_auto_confirmed(kwargs):
    assert assess(**kwargs).status != 'strong'


def test_degree_recovery_cites_only_the_completed_matching_record():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, education=[
        Education(institution='Unrelated School', qualification='Bachelor of Arts', dates='2020'),
        Education(institution='Pending School', qualification='MSc in Computer Science', dates='2099 expected'),
        Education(institution='Completed School', qualification='MSc in Computer Science', dates='2021'),
    ])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='Degree', source_quote='Degree in IT/Computer Science or equivalent experience.',
                         status='missing', reason='No degree recognized.')
    _facts(validator, req)
    assert req.status == 'strong'
    assert req.source_fact_ids
    assert all(validator.catalog.get(i).owner_index == 2 for i in req.source_fact_ids)
