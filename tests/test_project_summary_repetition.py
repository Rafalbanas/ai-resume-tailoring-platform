"""Avoid exact cross-section repetition without emptying projects or guessing facts."""
import pytest

from app.models.candidate import Project
from app.models.job import JobRequest
from app.models.resume import ResumeProject, TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.professional_summary import activity_clause, summary_contains_clause
from app.services.summary_review import sign_summary


@pytest.mark.parametrize('existing_project', [False, True])
def test_project_uses_other_relevant_source_fact_instead_of_repeating_summary(profile, existing_project):
    first = 'Integrated local models with Pydantic-validated JSON.'
    second = 'Implemented JSON evidence checks using stable source IDs.'
    profile.projects = [Project(name='API lab', facts=[first, second], technologies=['Python'])]
    catalog = FactCatalog(profile)
    entries = [e for e in catalog.prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    ids = [e.source_id for e in entries]
    text = 'Support Engineer at Example Ltd. Project work includes integrating local models with Pydantic-validated JSON.'
    resume = TailoredResume(headline='Support Engineer', professional_summary=text, summary_source_fact_ids=[ids[0]],
                            core_skills=[], experience=[], projects=[ResumeProject(name='API lab', description=first,
                                source_fact_ids=ids)] if existing_project else [])
    resume.summary_attestation = sign_summary(resume, profile, 'secret')
    job = JobRequest(company='Synthetic', role='API developer', job_description='Requirements\nLocal models and JSON evidence checks.')
    validator = FactValidator(profile, review_key='secret')
    checked = validator.validate(resume, job).resume
    assert checked.professional_summary == text
    assert checked.projects[0].description == second
    assert set(ids) <= set(checked.projects[0].source_fact_ids)
    again = validator.validate(checked, job).resume
    assert again.projects[0].description == second


def test_only_available_project_fact_is_not_removed(profile):
    fact = 'Integrated local models with Pydantic-validated JSON.'
    profile.projects = [Project(name='API lab', facts=[fact])]
    job = JobRequest(company='Synthetic', role='API developer', job_description='Requirements\nLocal models and JSON integration.')
    summary = 'Project work includes integrating local models with Pydantic-validated JSON.'
    assert FactValidator(profile)._project_description(profile.projects[0], job, summary=summary) == fact


@pytest.mark.parametrize('fact', ['Plans to integrate models.', 'Does not deploy models commercially.',
                                'Used to build models.', 'Supported by an external team.'])
def test_unknown_or_qualified_verb_is_not_mechanically_rewritten(fact):
    assert activity_clause(fact) is None


def test_clause_repetition_comparison_preserves_added_detail_negation_and_numbers():
    assert summary_contains_clause('Project work includes integrating JSON and using Python.', 'Integrated JSON.')
    assert not summary_contains_clause('Project work includes integrating JSON and XML.', 'Integrated JSON.')
    assert not summary_contains_clause('Project work includes integrating 2 APIs.', 'Integrated 3 APIs.')
    assert not summary_contains_clause('Project work: Does not deploy models.', 'Deploys models.')
    assert not summary_contains_clause('Project work includes not integrating JSON.', 'Integrated JSON.')
    assert not summary_contains_clause('Project work: Never integrated JSON.', 'Integrated JSON.')
