"""Terminology checks cannot be waived by model approval or a document worker."""
from pathlib import Path

import pytest

from app.models.job import JobRequest
from app.models.resume import ResumeProject, TailoredResume
from app.services.cv_content_policy import reviewable_bullet
from app.services.docx_generator import generate_docx
from app.services.fact_validator import FactValidator
from app.services.ollama_draft_review import sign_bullet, valid_bullet_attestation
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import prepare_resume
from app.services.summary_review import review_summary, sign_summary, valid_summary_attestation
from tests.test_cv_content_policy import draft

BAD = 'Compared machine learning models including XGBoost and scikit-learn.'
GOOD = 'Compared machine learning models using scikit-learn and XGBoost.'


@pytest.mark.parametrize('field', ['headline', 'professional_summary', 'bullet', 'project', 'core_skills'])
def test_export_checks_library_as_model_in_all_visible_sections(profile, field):
    resume = draft(profile, profile.experience[0].facts[0])
    if field == 'bullet':
        resume.experience[0].bullets[0].text = BAD
    elif field == 'project':
        resume.projects = [ResumeProject(name='Synthetic ML lab', description=BAD, source_fact_ids=['project:0:fact:0'])]
    elif field == 'core_skills':
        resume.core_skills = [BAD]
    else:
        setattr(resume, field, BAD)
    with pytest.raises(ValueError, match='Invalid ML terminology'):
        prepare_resume(resume, profile)


def test_signed_summary_with_bad_terminology_is_rebuilt(profile):
    resume = draft(profile, profile.experience[0].facts[0])
    resume.professional_summary = BAD
    resume.summary_source_fact_ids = ['experience:0:fact:0']
    resume.summary_attestation = sign_summary(resume, profile, 'secret')
    job = JobRequest(company='Example', role='Support', job_description='Requirements\nPython support automation')
    checked = FactValidator(profile, review_key='secret').validate(resume, job).resume
    assert checked.professional_summary != BAD
    assert not valid_summary_attestation(checked, profile, 'secret')


def test_even_exact_bad_source_bullet_cannot_gain_model_approval(profile):
    profile.experience[0].facts = [BAD]
    resume = draft(profile, BAD)
    bullet = resume.experience[0].bullets[0]
    resume._bullet_attestations = [sign_bullet(bullet, profile, 'secret')]
    assert not reviewable_bullet(bullet, profile)
    assert not valid_bullet_attestation(bullet, resume, profile, 'secret')


async def test_bad_summary_is_rejected_before_model_review(profile):
    class Provider:
        async def _chat(self, *args, **kwargs):
            pytest.fail('Deterministically invalid summary reached model review')

    resume = TailoredResume(headline='Support Engineer', professional_summary=BAD,
                            summary_source_fact_ids=['summary:0'], core_skills=[], experience=[])
    resume.summary_attestation = 'untrusted'
    reviewed = await review_summary(Provider(), resume, profile)
    assert reviewed.summary_attestation == ''


def test_invalid_source_is_not_rewritten_and_cannot_reach_document_workers(profile, tmp_path, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail('Invalid content reached document worker')

    monkeypatch.setattr('app.services.processing.process', unexpected)
    # Exact source wording remains intact: correcting the underlying fact needs
    # owner review, not a silent replacement by a guessed algorithm.
    profile.summary_facts = [BAD]
    resume = draft(profile, profile.experience[0].facts[0])
    for export in [lambda: PDFGenerator(Path('templates'), Path('static'), tmp_path).generate(
                        resume, profile, tmp_path / 'resume.pdf'),
                   lambda: generate_docx(resume, profile, tmp_path / 'resume.docx')]:
        with pytest.raises(ValueError, match='Invalid ML terminology'):
            export()
    assert profile.summary_facts == [BAD]
    assert not list(tmp_path.glob('resume.*'))


def test_valid_library_wording_can_be_prepared_for_export(profile):
    resume = draft(profile, profile.experience[0].facts[0])
    resume.professional_summary = GOOD
    prepared = prepare_resume(resume, profile)
    assert prepared.professional_summary == GOOD
