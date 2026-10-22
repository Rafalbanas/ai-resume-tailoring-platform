"""Synthetic regressions for evidence annotations and optional experience facts."""
import pytest

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import ResumeBullet, ResumeExperience, TailoredResume
from app.services.cv_content_policy import cv_catalog, reviewable_bullet
from app.services.fact_retrieval import FactIndex, retrieve_facts
from app.services.fact_validator import FactValidator
from app.services.ollama_draft_review import sign_bullet, valid_bullet_attestation
from app.services.resume_export import prepare_resume


def draft(profile, text, source='experience:0:fact:0'):
    return TailoredResume(headline='Support Engineer', professional_summary=profile.summary_facts[0],
        core_skills=['Python'], experience=[ResumeExperience(company='Example Ltd', title='Support Engineer',
            dates='', bullets=[ResumeBullet(text=text, source_fact_ids=[source])])])


@pytest.mark.parametrize('text', [
    'User-confirmed practical Python automation.',
    'Candidate–verified practical Python automation.',
    'Configured NAT and DHCP for support workflows with Python.',
    'Supported MikroTik networking and VPN operations.',
])
def test_model_approval_cannot_allow_annotation_or_wrong_citation(profile, text):
    profile.skills['network'] = ['MikroTik']
    resume = draft(profile, text)
    bullet = resume.experience[0].bullets[0]
    resume._bullet_attestations = [sign_bullet(bullet, profile, 'secret')]
    assert not valid_bullet_attestation(bullet, resume, profile, 'secret')
    job = JobRequest(company='Example', role='Support', job_description='Requirements: Python support automation')
    result = FactValidator(profile, review_key='secret').validate(resume, job).resume
    assert result.experience[0].bullets[0].text == profile.experience[0].facts[0]


def test_supported_reviewed_paraphrase_remains_available(profile):
    bullet = ResumeBullet(text='Automated support workflows with Python.', source_fact_ids=['experience:0:fact:0'])
    assert reviewable_bullet(bullet, profile)


@pytest.mark.parametrize('field', ['headline', 'professional_summary', 'bullet', 'core_skills'])
@pytest.mark.parametrize('annotation', ['User-confirmed practical Python.', 'source_fact_ids: internal data'])
def test_export_refuses_annotations_in_visible_fields(profile, field, annotation):
    resume = draft(profile, profile.experience[0].facts[0])
    if field == 'bullet':
        resume.experience[0].bullets[0].text = annotation
    elif field == 'core_skills':
        resume.core_skills = [annotation]
    else:
        setattr(resume, field, annotation)
    with pytest.raises(ValueError, match='Internal evidence annotation'):
        prepare_resume(resume, profile)


@pytest.mark.parametrize('failure', [False, True])
@pytest.mark.parametrize('mention', [False, True])
def test_optional_fact_obeys_posting_in_retrieval_and_signed_or_empty_drafts(profile, monkeypatch, failure, mention):
    fact = 'Conducted packet-level analysis with Wireshark in a one-off diagnostic task.'
    profile.experience[0].facts.append(fact)
    profile.experience[0].cv_fact_conditions[fact] = ['Wireshark']
    if failure:
        def unavailable(*args):
            raise RuntimeError('index unavailable')
        monkeypatch.setattr(FactIndex, 'search', unavailable)
    job = JobRequest(company='Example', role='Support', job_description='Requirements: Python automation' + (' and wireshark diagnostics' if mention else ''))
    analysis = JobAnalysis(company='Example', role='Support', strong_matches=[], partial_matches=[], missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    retrieved = retrieve_facts(job, profile, analysis)
    assert (fact in [e.text for e in retrieved.entries]) == mention
    validator = FactValidator(profile, review_key='secret')
    resume = draft(profile, fact, 'experience:0:fact:1')
    resume._bullet_attestations = [sign_bullet(resume.experience[0].bullets[0], profile, 'secret')]
    for candidate in [resume, resume.model_copy(update={'experience': []})]:
        output = validator.validate(candidate, job).resume
        assert (fact in [b.text for e in output.experience for b in e.bullets]) == mention
    assert bool(cv_catalog(profile, job).get('experience:0:fact:1')) == mention


def test_skill_generation_labels_use_canonical_fact_instead_of_admin_description(profile, tmp_path):
    from app.models.skills import SkillEvidence
    from tests.test_skills_bank import bank, skill
    value = skill('Python')
    value.evidence = [SkillEvidence(source_type='master_profile', source_id='summary:0',
                                  description='User-confirmed practical Python configuration.')]
    store = bank(tmp_path, profile, [value])
    assert store.evidence_labels(value) == [profile.summary_facts[0]]


def test_remote_exports_block_leak_before_calling_worker(profile, tmp_path, monkeypatch):
    from pathlib import Path

    from app.services.docx_generator import generate_docx
    from app.services.pdf_generator import PDFGenerator
    def unexpected(*args, **kwargs):
        pytest.fail('Invalid content reached document worker')
    monkeypatch.setattr('app.services.processing.process', unexpected)
    resume = draft(profile, 'User-confirmed practical Python automation.')
    for export in [lambda: PDFGenerator(Path('templates'), Path('static'), tmp_path).generate(resume, profile, tmp_path / 'resume.pdf'),
                   lambda: generate_docx(resume, profile, tmp_path / 'resume.docx')]:
        with pytest.raises(ValueError, match='Internal evidence annotation'):
            export()
    assert not list(tmp_path.glob('resume.*'))
