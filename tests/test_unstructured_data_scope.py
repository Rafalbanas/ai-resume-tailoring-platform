import pytest

from app.models.candidate import CandidateProfile, Project
from app.models.job import JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.semantic_requirements import _facts


@pytest.mark.parametrize('quote', [
    'Pracujesz z SQL, danymi ustrukturyzowanymi i nieustrukturyzowanymi.',
    'Experience working with SQL, structured and unstructured data.',
])
def test_relational_queries_do_not_confirm_the_unstructured_data_conjunct(quote):
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[
        Project(name='Database project', facts=['Used SQL queries and SQLAlchemy for relational data modeling.'])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='SQL and data handling', source_quote=quote, status='strong', reason='Relational queries confirmed.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'partial'
    assert 'unstructured data' in req.reason


def test_documented_unstructured_data_work_is_not_rejected():
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'}, projects=[
        Project(name='Document processing project', facts=['Processed unstructured data and used SQL for relational queries.'])])
    validator = AnalysisValidator(profile)
    req = JobRequirement(name='SQL and data handling', source_quote='Experience with SQL and unstructured data.',
                         status='strong', reason='Both scopes documented.',
                         source_fact_ids=[e.source_id for e in validator.matcher.entries])
    _facts(validator, req)
    assert req.status == 'strong'
