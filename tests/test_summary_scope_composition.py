"""Do not improve style by borrowing duties or weakening summary provenance."""
import pytest

from app.models.candidate import Experience, Project
from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.professional_summary import build_summary, employment_scope_issue
from app.services.summary_confirmation import summary_review
from app.services.summary_review import sign_summary, valid_source_summary, valid_summary_attestation


def with_history(profile):
    profile.summary_facts = []
    profile.experience.extend([
        Experience(company='Former Database Ltd', title='IT Specialist', start='2019-01', end='2020-12',
                   facts=['Used SQL and T-SQL queries for operational verification.']),
        Experience(company='Former Automation Ltd', title='IT Specialist', start='2017-01', end='2018-12',
                   facts=['Automated operational tasks with PowerShell and Python.']),
    ])
    return profile


def test_two_project_facts_have_one_scope_label_and_keep_both_citations(profile):
    profile.summary_facts = []
    facts = ['Integrated local models with Pydantic-validated JSON.',
             'Integrates REST API endpoints using Python and HTTPX.']
    profile.projects = [Project(name='API lab', facts=facts, technologies=['Python', 'HTTPX'])]
    catalog = FactCatalog(profile)
    project_entries = [e for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    priorities = {e.source_id: 100 - i for i, e in enumerate(project_entries)}
    text, ids = build_summary(catalog, 'AI developer\nPython HTTPX REST API JSON local models.', priorities=priorities)
    assert text.count('Project work includes') == 1
    for fact in facts:
        assert fact.split(' ', 1)[1].rstrip('.').casefold() in text.casefold()
    assert {e.source_id for e in project_entries} <= set(ids)
    assert len(text) <= 700


def test_previous_employers_share_a_scope_block_not_the_current_employer(profile):
    profile = with_history(profile)
    catalog = FactCatalog(profile)
    old = [e for e in catalog.prompt_entries if e.kind == 'experience' and e.owner_index in {1, 2}]
    priorities = {e.source_id: 100 - i for i, e in enumerate(old)}
    text, ids = build_summary(catalog, 'Data developer\nSQL PowerShell Python automation.', priorities=priorities)
    assert text.startswith('Support Engineer at Example Ltd.')
    assert text.count('Previous roles involved') == 1
    for entry in old:
        assert entry.text.split(' ', 1)[1].rstrip('.').casefold() in text.casefold()
        assert entry.source_id in ids
    assert not employment_scope_issue(text, catalog.valid(ids), profile)


def test_support_summary_does_not_call_current_l1_l2_duties_previous_work(profile):
    profile.summary_facts = []
    profile.experience[0].facts = ['Provided L1 and L2 user support.', 'Analyzes application logs for incident investigation.']
    text, _ = build_summary(FactCatalog(profile), 'Technical Support Engineer\nApplication support.')
    assert 'previous roles included L1 and L2 support' not in text


@pytest.mark.parametrize('scope', ['Previous roles included', 'Earlier work included', 'At Former Database Ltd,'])
def test_explicit_previous_scope_remains_reviewable(profile, scope):
    profile = with_history(profile)
    catalog = FactCatalog(profile)
    entries = [e for e in catalog.prompt_entries if e.kind == 'experience' and e.owner_index == 1]
    text = f'Support Engineer at Example Ltd. {scope} SQL and T-SQL queries for operational verification.'
    assert not employment_scope_issue(text, entries, profile)


def test_model_approval_does_not_allow_previous_duties_to_migrate_to_current_company(profile):
    profile = with_history(profile)
    catalog = FactCatalog(profile)
    old = next(e for e in catalog.prompt_entries if e.kind == 'experience' and e.owner_index == 1)
    text = 'Support Engineer at Example Ltd. Used SQL and T-SQL queries for operational verification.'
    resume = TailoredResume(headline='Support Engineer', professional_summary=text,
                            summary_source_fact_ids=[old.source_id], core_skills=[], experience=[])
    resume.summary_attestation = sign_summary(resume, profile, 'synthetic-key')
    assert employment_scope_issue(text, [old], profile)
    job = JobRequest(company='Synthetic', role='Data developer', job_description='Requirements\nSQL and T-SQL operational verification.')
    checked = FactValidator(profile, review_key='synthetic-key').validate(resume, job).resume
    assert checked.professional_summary != text
    assert 'Previous roles involved' in checked.professional_summary
    assert valid_source_summary(checked, profile, 'synthetic-key')
    assert not valid_summary_attestation(checked, profile, 'synthetic-key')
    assert not employment_scope_issue(checked.professional_summary, catalog.valid(checked.summary_source_fact_ids), profile)
    again = FactValidator(profile, review_key='synthetic-key').validate(checked, job).resume
    assert again.professional_summary == checked.professional_summary


def test_correctly_scoped_approved_summary_keeps_owner_confirmation(profile):
    profile = with_history(profile)
    old = next(e for e in FactCatalog(profile).prompt_entries if e.kind == 'experience' and e.owner_index == 1)
    text = 'Support Engineer at Example Ltd. Previous roles included SQL and T-SQL operational verification.'
    resume = TailoredResume(headline='Support Engineer', professional_summary=text,
                            summary_source_fact_ids=[old.source_id], core_skills=[], experience=[])
    resume.summary_attestation = sign_summary(resume, profile, 'synthetic-key')
    job = JobRequest(company='Synthetic', role='Data developer', job_description='Requirements\nSQL operational verification.')
    checked = FactValidator(profile, review_key='synthetic-key').validate(resume, job).resume
    assert checked.professional_summary == text
    assert valid_summary_attestation(checked, profile, 'synthetic-key')
    assert summary_review(checked, profile, 'synthetic-key', 'synthetic-document')['required']


def test_model_approval_cannot_keep_repeated_project_labels(profile):
    facts = ['Integrated local models with Pydantic-validated JSON.',
             'Integrates REST API endpoints using Python and HTTPX.']
    profile.projects = [Project(name='API lab', facts=facts, technologies=['Python', 'HTTPX'])]
    catalog = FactCatalog(profile)
    ids = [e.source_id for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    text = ' '.join('Project work: ' + fact for fact in facts)
    resume = TailoredResume(headline='Support Engineer', professional_summary=text,
                            summary_source_fact_ids=ids, core_skills=[], experience=[])
    resume.summary_attestation = sign_summary(resume, profile, 'synthetic-key')
    job = JobRequest(company='Synthetic', role='AI developer', job_description='Requirements\nPython HTTPX REST API local models.')
    checked = FactValidator(profile, review_key='synthetic-key').validate(resume, job).resume
    assert checked.professional_summary.count('Project work includes') == 1
    assert not valid_summary_attestation(checked, profile, 'synthetic-key')
