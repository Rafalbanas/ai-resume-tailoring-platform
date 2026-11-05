"""Synthetic regressions from manual batch review; no private CV fixtures."""
import pytest

from app.models.candidate import Project
from app.models.job import JobRequest, JobRequirement
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import required_years
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, needs_assessment
from app.services.semantic_requirements import _facts


@pytest.mark.parametrize('phrase', [
    'Strong hands-on experience with Azure Integration Services.',
    'Dobra praktyczna znajomość języka SQL,',
    'Previous experience in a 2nd line B2B support role within a SaaS product company.',
    'Working knowledge of SSO, user provisioning, and access management.',
    'Outstanding written and verbal communication skills. Strong proficiency in English is required.',
    'Zdolności komunikacyjne niezbędne do pracy z klientem i pracy w zespole',
    'Samodzielność, staranność i terminowość w realizacji zadań.',
    'Gotowość do pracy w systemie zmianowym i pracy stacjonarnej.',
])
def test_literal_qualifications_cannot_be_hidden_as_context_or_duties(profile, phrase):
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Required technical and professional expertise:\n' + phrase)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, value in inv.passages.items() if value['text'] == phrase)
    assert needs_assessment(inv.passages[pid])
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['k']['enum'] == ['requirement']
    candidate = inv.expand([CompactAssessment(p=p, k='context') for p in inv.passages]).to_analysis(job)
    report = AnalysisValidator(profile).validate(candidate, job.job_description, semantic=True)
    assert not report.is_reliable
    assert phrase in report.unassessed_source_passages


def test_company_calendar_year_is_context_not_candidate_tenure(profile):
    quote = 'Jesteśmy liderem rekrutacji i doradztwa HR. Marka obecna jest w Polsce od 1996 roku.'
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Kim jesteśmy?\n' + quote)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, value in inv.passages.items() if value['text'] == quote)
    row = inv.validate_rows([CompactAssessment(p=pid, k='requirement', n='HR', s='strong', why='Wrong model classification.')], [pid])[0]
    assert row.k == 'context'
    assert required_years(quote) is None
    assert required_years('Minimum 3 years of commercial experience') == 3


@pytest.mark.parametrize('phrase', [
    'Strong hands-on experience with Azure Integration Services.',
    'Previous experience in a 2nd line support role.',
    'Outstanding written communication skills. Strong proficiency in English is required.',
])
def test_explicit_prior_experience_is_qualified_even_under_unfamiliar_heading(profile, phrase):
    job = JobRequest(company='Synthetic', role='Engineer', job_description='What makes you thrive here:\n' + phrase)
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, value in inv.passages.items() if value['text'] == phrase)
    schema = inv.keyed_schema([pid])
    ref = schema['properties']['assessments']['properties'][pid]['$ref'].split('/')[-1]
    assert schema['$defs'][ref]['properties']['k']['enum'] == ['requirement']


@pytest.fixture
def scoped_profile(profile):
    result = profile.model_copy(deep=True)
    result.experience[0].facts.extend([
        'Administered Active Directory users, groups and access.',
        'Managed partner support cases in Salesforce.',
        'Administered VMware ESXi virtual machines.',
    ])
    result.projects = [Project(name='Synthetic application', description='A test-backed application.', facts=[
        'Configured GitHub Actions CI/CD; the pipeline runs tests and deploys Docker images.',
        'Implemented API unit and integration tests using pytest.',
        'Evaluated regression models using Python in an academic project.',
    ])]
    return result


@pytest.mark.parametrize('name,quote', [
    ('CI/CD', 'Experience with Azure DevOps and CI/CD pipeline implementation.'),
    ('User access', 'Working knowledge of SSO, user provisioning, and access management.'),
    ('Virtualization', 'Knowledge of VMware and Azure.'),
    ('Application verification', 'API testing and load testing experience.'),
    ('Application verification', 'API testing and performance testing experience.'),
])
def test_short_model_label_cannot_erase_named_scope(scoped_profile, name, quote):
    validator = AnalysisValidator(scoped_profile)
    req = JobRequirement(name=name, source_quote=quote, status='strong',
                         source_fact_ids=[entry.source_id for entry in validator.matcher.entries], reason='Model claims a complete match.')
    _facts(validator, req)
    assert req.status.value != 'strong'
    assert 'Named source scope is not confirmed' in req.reason


def test_generic_ticketing_accepts_actual_case_handling_but_does_not_invent_zendesk(scoped_profile):
    validator = AnalysisValidator(scoped_profile)
    req = JobRequirement(name='Support ticketing systems', source_quote='Experience with support ticketing systems such as Zendesk.',
                         status='missing', reason='The model overlooked Salesforce.')
    _facts(validator, req)
    assert req.status.value == 'strong'
    assert any('Salesforce' in text for text in req.evidence)
    req = JobRequirement(name='Zendesk ticketing', source_quote='Practical experience using Zendesk ticketing.',
                         status='strong', source_fact_ids=req.source_fact_ids, reason='Incorrect product equivalence.')
    _facts(validator, req)
    assert req.status.value != 'strong'


def test_actual_azure_devops_evidence_and_optional_examples_are_not_rejected(scoped_profile):
    from app.services.named_evidence import named_scope_ceiling
    scoped_profile.projects[0].facts.append('Configured Azure DevOps pipelines and verified successful test runs.')
    validator = AnalysisValidator(scoped_profile)
    entries = validator.matcher.entries
    assert named_scope_ceiling('Experience with Azure DevOps and CI/CD.', entries) is None
    assert validator.matcher.match('Experience with Azure DevOps and CI/CD.').status.value == 'strong'
    assert named_scope_ceiling('CI/CD tools such as Azure DevOps.', entries) is None
    assert named_scope_ceiling('Knowledge of Azure or AWS.', entries) is None
