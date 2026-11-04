"""Remove only bounded redundancy; retain scope, methods, metrics and evidence."""
import pytest

from app.models.candidate import Project
from app.models.job import JobRequest
from app.models.resume import ResumeProject, TailoredResume
from app.services.content_quality import deduplicate_project_text, project_sentences
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.resume_export import prepare_resume
from app.services.summary_review import review_summary, sign_summary, valid_source_summary, valid_summary_attestation

NOMINAL = 'Python data pipeline for cycling FTP estimation and comparison of multiple machine learning models.'
EVALUATION = 'Evaluated multiple machine learning models as part of the MSc thesis.'
MERGED = ('Python data pipeline for cycling FTP estimation and comparison of multiple machine learning models '
          'as part of the MSc thesis.')


@pytest.mark.parametrize('value', [NOMINAL + ' ' + EVALUATION, EVALUATION + ' ' + NOMINAL])
def test_model_comparison_repetition_keeps_thesis_scope(value):
    clean = deduplicate_project_text(value)
    assert clean == MERGED
    assert deduplicate_project_text(clean) == clean


@pytest.mark.parametrize('extra', [
    'Evaluated 5 machine learning models as part of the MSc thesis.',
    'Evaluated multiple machine learning models using cross-validation.',
    'Evaluated multiple machine learning models with SHAP explanations.',
    'Evaluated multiple machine learning models on a separate dataset.',
    'Did not evaluate multiple machine learning models.',
    'Plans to evaluate multiple machine learning models.',
    'Deployed multiple machine learning models.',
])
def test_distinct_model_activities_and_qualifiers_remain(extra):
    value = NOMINAL + ' ' + extra
    assert deduplicate_project_text(value) == value


@pytest.mark.parametrize('qualifier', ['Planned', 'Experimental', 'Local', 'Failed', 'Advanced', 'Academic'])
def test_qualified_comparison_is_not_merged_with_unqualified_evaluation(qualifier):
    value = qualifier + ' ' + NOMINAL + ' ' + EVALUATION
    assert deduplicate_project_text(value) == value


def test_different_thesis_contexts_are_not_silently_combined():
    nominal = NOMINAL.rstrip('.') + ' for the MSc thesis.'
    action = 'Evaluated multiple machine learning models for the Master’s thesis.'
    assert deduplicate_project_text(nominal + ' ' + action) == nominal + ' ' + action


def test_fact_validation_and_export_share_project_cleanup_without_changing_sources(profile):
    profile.projects = [Project(name='Thesis lab', description=NOMINAL, facts=[EVALUATION], technologies=['Python'])]
    catalog = FactCatalog(profile)
    ids = [e.source_id for e in catalog.prompt_entries if e.kind == 'project' and ':technology:' not in e.source_id]
    resume = TailoredResume(headline='Support Engineer', professional_summary=profile.summary_facts[0],
                            summary_source_fact_ids=['summary:0'], core_skills=[], experience=[],
                            projects=[ResumeProject(name='Thesis lab', description=NOMINAL + ' ' + EVALUATION,
                                                    source_fact_ids=ids)])
    original = profile.model_dump()
    job = JobRequest(company='Synthetic', role='Python developer', job_description='Requirements\nPython machine learning models and data pipelines.')
    validator = FactValidator(profile)
    checked = validator.validate(resume, job).resume
    assert checked.projects[0].description == MERGED
    assert set(ids) <= set(checked.projects[0].source_fact_ids)
    assert validator.validate(checked, job).resume.projects[0].description == MERGED
    prepared = prepare_resume(resume, profile)
    assert prepared.projects[0].description == MERGED
    assert profile.model_dump() == original
    assert resume.projects[0].description == NOMINAL + ' ' + EVALUATION


def test_source_paragraphs_do_not_expand_into_six_sentences(profile):
    sentences = ['Built Python API endpoints.', 'Tested Python API endpoints.', 'Documented Python API deployment.']
    profile.projects = [Project(name='API lab', description=' '.join(sentences),
                                facts=['Configured Python API health checks. Implemented Python API rollback.'])]
    job = JobRequest(company='Synthetic', role='Python developer', job_description='Requirements\nPython API deployment and workflows.')
    description = FactValidator(profile)._project_description(profile.projects[0], job)
    assert 1 <= len(project_sentences(description)) <= 2
    assert len(description) <= 500
    assert all(sentence in sentences + ['Configured Python API health checks.', 'Implemented Python API rollback.']
               for sentence in project_sentences(description))


@pytest.mark.parametrize('preserve', [False, True])
def test_generated_attested_paragraph_is_compact_but_manual_preserve_is_unchanged(profile, preserve):
    paragraph = 'Built Python API endpoints. Tested Python API endpoints. Documented Python API deployment.'
    profile.projects = [Project(name='API lab', facts=[paragraph])]
    ids = [e.source_id for e in FactCatalog(profile).prompt_entries if e.kind == 'project' and ':fact:' in e.source_id]
    resume = TailoredResume(headline='Support Engineer', professional_summary=profile.summary_facts[0],
                            summary_source_fact_ids=['summary:0'], core_skills=[], experience=[],
                            projects=[ResumeProject(name='API lab', description=paragraph, source_fact_ids=ids)])
    job = JobRequest(company='Synthetic', role='Python developer', job_description='Requirements\nPython API development and deployment.')
    checked = FactValidator(profile).validate(resume, job, preserve_skills=preserve).resume
    assert len(project_sentences(checked.projects[0].description)) == (3 if preserve else 2)
    assert checked.projects[0].description in paragraph


def test_long_sole_source_sentence_is_preserved_not_clipped(profile):
    fact = 'Built a Python workflow using ' + 'verified synthetic tooling, ' * 25 + 'with documented checks.'
    profile.projects = [Project(name='Workflow lab', facts=[fact])]
    job = JobRequest(company='Synthetic', role='Python developer', job_description='Requirements\nPython workflow tooling and checks.')
    assert FactValidator(profile)._project_description(profile.projects[0], job) == fact


def test_summary_sentence_is_not_repeated_from_a_multi_sentence_description(profile):
    first, second = 'Integrated local models with JSON outputs.', 'Implemented JSON evidence checks.'
    profile.projects = [Project(name='API lab', description=first + ' ' + second)]
    job = JobRequest(company='Synthetic', role='API developer', job_description='Requirements\nLocal models and JSON evidence checks.')
    text = FactValidator(profile)._project_description(profile.projects[0], job,
                                                     summary='Project work includes integrating local models with JSON outputs.')
    assert text == second


def coordinated_resume(profile):
    fact = 'Built and tested local and VPS workflows.'
    profile.summary_facts = []
    profile.projects = [Project(name='Workflow lab', facts=[fact])]
    entry = next(e for e in FactCatalog(profile).prompt_entries if e.kind == 'project' and ':fact:' in e.source_id)
    resume = TailoredResume(headline='Support Engineer', professional_summary=(
        'Support Engineer at Example Ltd. Project work includes building and tested local and VPS workflows.'),
        summary_source_fact_ids=[entry.source_id], core_skills=[], experience=[])
    return resume


def test_model_signature_cannot_waive_a_known_broken_activity_transformation(profile):
    resume = coordinated_resume(profile)
    resume.summary_attestation = sign_summary(resume, profile, 'secret')
    job = JobRequest(company='Synthetic', role='API developer', job_description='Requirements\nLocal and VPS workflow development.')
    checked = FactValidator(profile, review_key='secret').validate(resume, job).resume
    assert 'building and tested' not in checked.professional_summary
    assert 'building and testing local and VPS workflows' in checked.professional_summary
    assert valid_source_summary(checked, profile, 'secret')
    assert not valid_summary_attestation(checked, profile, 'secret')


async def test_known_broken_activity_is_rejected_before_model_approval(profile):
    class Provider:
        async def _chat(self, *args, **kwargs):
            pytest.fail('Known broken activity reached model review')

    resume = coordinated_resume(profile)
    reviewed = await review_summary(Provider(), resume, profile)
    assert not reviewed.summary_attestation
