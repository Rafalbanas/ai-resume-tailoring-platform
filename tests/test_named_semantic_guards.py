"""Valid source IDs alone cannot prove a different, related named product."""
import pytest

from app.models.candidate import CandidateProfile
from app.models.interpretation import JobInterpretation, ModelRequirement
from app.models.job import JobRequest
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog


@pytest.mark.parametrize(('required', 'documented'), [
    ('LangGraph', 'LangChain'), ('LangChain', 'LangGraph'),
    ('Azure AI Services', 'Azure Active Directory'),
])
@pytest.mark.parametrize('same_product', [False, True])
def test_related_named_product_cannot_be_confirmed_by_valid_but_wrong_citation(required, documented, same_product):
    fact = f'Implemented an integration using {required if same_product else documented} in a personal project.'
    profile = CandidateProfile(personal={}, projects=[{'name': 'Personal lab', 'facts': [fact]}])
    catalog = FactCatalog(profile)
    sid = next(e.source_id for e in catalog.prompt_entries if e.text == fact)
    quote = f'Experience with {required}'
    job = JobRequest(company='Example', role='Developer', job_description='Requirements\n' + quote)
    interpretation = JobInterpretation(requirements=[ModelRequirement(
        name=quote, source_quote=quote, priority='mandatory', status='strong', source_fact_ids=[sid],
        reason='Model claimed the cited integration is sufficient.', operator='single', components=[],
        classification_basis='Literal requirement')], source_context=[{'source_quote': 'Requirements'}])
    result = AnalysisValidator(profile).validate(interpretation.to_analysis(job), job.job_description, semantic=True)
    req = result.requirements[0]
    assert req.status == ('strong' if same_product else 'missing')
    assert req.source_fact_ids == ([sid] if same_product else [])


def test_named_product_project_is_not_commercial_practice_or_tenure():
    from app.services.evidence_matching import EvidenceMatcher
    profile = CandidateProfile(personal={}, projects=[{
        'name': 'Personal lab', 'facts': ['Implemented a LangGraph application in a personal project.']}])
    matcher = EvidenceMatcher(FactCatalog(profile))
    assert matcher.match('Commercial experience with LangGraph').status == 'partial'
    assert matcher.match('2 years of LangGraph experience').status == 'missing'


def test_related_named_product_employment_does_not_prove_specialist_tenure():
    from app.services.evidence_matching import EvidenceMatcher
    profile = CandidateProfile(personal={}, experience=[{
        'company': 'Example', 'title': 'Developer', 'start': '2020-01', 'end': '2024-12',
        'facts': ['Implemented a LangChain application.']}])
    matcher = EvidenceMatcher(FactCatalog(profile))
    ids = [e.source_id for e in matcher.entries]
    assert matcher.cited_tenure(ids, 2, scope='2 years of LangGraph experience').status == 'missing'
    assert matcher.match('2 years of LangChain experience').status == 'strong'


def test_concise_model_label_cannot_drop_commercial_source_qualifier():
    fact = 'Implemented a LangGraph application in a personal project.'
    profile = CandidateProfile(personal={}, projects=[{'name': 'Personal lab', 'facts': [fact]}])
    sid = next(e.source_id for e in FactCatalog(profile).prompt_entries if e.text == fact)
    quote = 'Commercial experience with LangGraph'
    job = JobRequest(company='Example', role='Developer', job_description='Requirements\n' + quote)
    interpretation = JobInterpretation(requirements=[ModelRequirement(
        name='LangGraph', source_quote=quote, priority='mandatory', status='strong', source_fact_ids=[sid],
        reason='Model claimed project practice is sufficient.', operator='single', components=[],
        classification_basis='Literal requirement')], source_context=[{'source_quote': 'Requirements'}])
    req = AnalysisValidator(profile).validate(
        interpretation.to_analysis(job), job.job_description, semantic=True).requirements[0]
    assert req.status == 'partial'
