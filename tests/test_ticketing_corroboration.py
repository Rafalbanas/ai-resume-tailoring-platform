from app.models.candidate import CandidateProfile, Project
from app.models.job import JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.semantic_requirements import _facts


def test_ticketing_declaration_is_retained_without_inventing_practice():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, skills={'tools': ['Ticketing systems']})
    validator = AnalysisValidator(profile)
    ids = [e.source_id for e in validator.matcher.entries if 'Ticketing' in e.text]
    req = JobRequirement(name='Ticketing systems', source_quote='Experience using ticketing systems.',
                         status='partial', reason='Declared knowledge only.', source_fact_ids=ids)
    _facts(validator, req)
    assert req.status != 'strong'
    assert set(ids) <= set(req.source_fact_ids)
    assert not validator._evidence_issues


def test_git_use_does_not_become_proficiency():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'},
                               projects=[Project(name='Synthetic', facts=['Used Git for version control.'])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='Git proficiency', source_quote='Git proficiency.', status='partial',
                         reason='Use, not proficiency.', source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'partial'
    assert req.source_fact_ids
