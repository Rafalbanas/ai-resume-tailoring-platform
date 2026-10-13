
import pytest
from docx import Document
from fastapi.testclient import TestClient
from pypdf import PdfReader

from app.main import app
from app.models.candidate import Project
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import ResumeProject, TailoredResume
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.resume_editor import apply_resume_edits
from tests.test_recording_demo import sign_in


@pytest.fixture
def saved_cv(resume_payload, monkeypatch):
    with TestClient(app) as client:
        sign_in(client)
        app.state.profile.projects = [Project(name='Synthetic lab', description='Built a Python utility.', technologies=['Python', 'Linux'], facts=['Built a Python utility.'])]
        app.state.skills_bank.profile = app.state.profile
        app.state.skills_bank.catalog = FactCatalog(app.state.profile)
        project_ids = [e.source_id for e in app.state.skills_bank.catalog.prompt_entries if e.kind == 'project' and ':technology:' not in e.source_id]
        resume = TailoredResume.model_validate(resume_payload)
        resume.projects = [ResumeProject(name='Synthetic lab', description='Built a Python utility.', technologies=['Python'], source_fact_ids=project_ids)]
        resume.core_skills = ['Python', 'Playwright browser automation', 'Legacy tool']
        resume.selected_skill_ids = ['stale_id', 'skill_synthetic_0']
        resume.professional_summary = 'A saved legacy summary that the current validator would rewrite.'
        job = JobRequest(company='Synthetic', role='Support Engineer', job_description='Requirements\nExperience with Python and Linux in IT support.')
        analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[], missing_requirements=[], recommendation='REVIEW', match_level='LOW')
        slug, folder = app.state.storage.save_application(job, analysis, resume, [])
        # Use real PDF and DOCX exporters; avoid adaptive pagination overhead.
        yield client, slug, folder, resume, job


def form_for(client, resume, **changes):
    form = {'csrf_token': client.cookies.get('csrf_token'), 'headline': resume.headline,
            'professional_summary': resume.professional_summary, 'core_skills': '\n'.join(resume.core_skills),
            'interests': ', '.join(resume.interests), 'template_name': 'ats_classic'}
    for i, experience in enumerate(resume.experience):
        for j, bullet in enumerate(experience.bullets):
            form[f'experience_{i}_bullet_{j}'] = bullet.text
    for i, project in enumerate(resume.projects):
        form[f'project_{i}_description'] = project.description
        form[f'project_{i}_technologies'] = ', '.join(project.technologies)
    return dict(form, **changes)


@pytest.mark.parametrize('remaining', [['Python', 'Legacy tool'], ['Python'], []])
def test_remove_skills_preserves_unedited_content_and_exports(saved_cv, remaining):
    client, slug, folder, original, job = saved_cv
    private = [app.state.settings.master_profile_path, app.state.settings.skills_path]
    before_private = [p.read_bytes() for p in private]
    response = client.post(f'/edit/{slug}', data=form_for(client, original, core_skills='\n'.join(remaining)), follow_redirects=False)
    assert response.status_code == 303, response.text
    _, saved, generated, metadata = app.state.storage.load_application(slug)
    assert saved.core_skills == remaining
    for section in ('headline', 'professional_summary', 'summary_source_fact_ids', 'experience', 'projects', 'education', 'certifications', 'interests'):
        assert getattr(saved, section) == getattr(original, section)
    assert generated == original
    assert [p.read_bytes() for p in private] == before_private
    assert metadata['truth_lock_warnings'] and 'professional_summary' in ' '.join(metadata['truth_lock_warnings'])
    pdf_text = '\n'.join(page.extract_text() for page in PdfReader(folder/'resume.pdf').pages)
    doc = Document(folder/'resume.docx')
    doc_text = '\n'.join(p.text for p in doc.paragraphs) + '\n' + '\n'.join(p.text for table in doc.tables for row in table.rows for cell in row.cells for p in cell.paragraphs)
    assert 'Playwright browser automation' not in pdf_text and 'Playwright browser automation' not in doc_text
    assert original.professional_summary in doc_text
    reopen = client.get(f'/edit/{slug}')
    assert reopen.status_code == 200
    assert 'Existing document' in reopen.text
    assert 'Playwright browser automation' not in reopen.text
    assert len(list((folder/'versions').iterdir())) == 1


@pytest.mark.parametrize('addition', ['Kubernetes', 'Advanced Python', 'Expert Python'])
def test_unverified_technology_and_inflated_level_rejected(saved_cv, addition):
    client, slug, folder, original, _ = saved_cv
    before = (folder/'resume.json').read_bytes()
    response = client.post(f'/edit/{slug}', data=form_for(client, original, core_skills='Python\n'+addition), follow_redirects=False)
    assert response.status_code == 422
    assert f'Skills: {addition}' in response.text
    assert 'Remove this addition' in response.text or 'Use the verified wording' in response.text
    assert (folder/'resume.json').read_bytes() == before
    assert not (folder/'resume.pdf').exists()


def test_unsupported_summary_edit_names_field_and_preserves_document(saved_cv):
    client, slug, folder, original, _ = saved_cv
    before = (folder/'resume.json').read_bytes()
    response = client.post(f'/edit/{slug}', data=form_for(client, original, professional_summary='Expert Kubernetes administrator with advanced production expertise.'), follow_redirects=False)
    assert response.status_code == 422
    assert 'professional_summary' in response.text
    assert 'source-backed wording' in response.text
    assert (folder/'resume.json').read_bytes() == before


def test_failed_docx_export_rolls_back_every_saved_artifact(saved_cv, monkeypatch):
    client, slug, folder, original, _ = saved_cv
    for name in ('resume.pdf', 'resume.docx'):
        (folder/name).write_bytes(b'original artifact')
    before = {name: (folder/name).read_bytes() for name in ('resume.json','metadata.json','resume.pdf','resume.docx')}
    def fail(*args, **kwargs):
        raise ValueError('DOCX export failed')
    monkeypatch.setattr(app.state, 'docx_generator', fail)
    response = client.post(f'/edit/{slug}', data=form_for(client, original, core_skills='Python'), follow_redirects=False)
    assert response.status_code == 422
    assert {name: (folder/name).read_bytes() for name in before} == before


def test_omitting_bullets_and_project_technologies_does_not_restore_them(saved_cv):
    _, _, _, original, job = saved_cv
    edited = apply_resume_edits(original, {'experience_0_bullet_0': '', 'core_skills': '', 'project_0_description': '', 'project_0_technologies': ''})
    checked = FactValidator(app.state.profile, app.state.skills_bank).validate_manual_edit(original, edited, job)
    assert not checked.issues
    assert checked.resume.experience[0].bullets == []
    assert checked.resume.core_skills == [] and checked.resume.selected_skill_ids == []
    assert checked.resume.projects[0].description == "" and checked.resume.projects[0].technologies == []


def test_unchanged_skill_ids_and_summary_attestation_are_preserved(resume_payload):
    original = TailoredResume.model_validate(resume_payload)
    original.core_skills = ['Git, GitHub', 'Python']
    original.selected_skill_ids = ['old-unaligned-id']
    original.summary_attestation = 'existing-attestation'
    same = apply_resume_edits(original, {'core_skills': 'Git, GitHub\nPython'})
    assert same == original
    removed = apply_resume_edits(original, {'core_skills': 'Git, GitHub'})
    assert removed.core_skills == ['Git, GitHub']
    assert removed.selected_skill_ids == []
    assert removed.summary_attestation == original.summary_attestation


def test_changed_employment_bullet_cannot_invent_practical_proficiency(saved_cv):
    client, slug, folder, original, _ = saved_cv
    before = (folder/'resume.json').read_bytes()
    response = client.post(f'/edit/{slug}', data=form_for(client, original, experience_0_bullet_0='Expert production Kubernetes administrator with advanced cluster management.'), follow_redirects=False)
    assert response.status_code == 422
    assert 'experience_0_bullet_0' in response.text
    assert 'employment citations' in response.text
    assert (folder/'resume.json').read_bytes() == before


def test_safe_source_backed_bullet_change_is_accepted(saved_cv):
    client, slug, _, original, _ = saved_cv
    fact = app.state.profile.experience[0].facts[0]
    response = client.post(f'/edit/{slug}', data=form_for(client, original, experience_0_bullet_0=fact), follow_redirects=False)
    assert response.status_code == 303, response.text
    saved = app.state.storage.load_application(slug)[1]
    assert saved.experience[0].bullets[0].text == fact
    assert saved.projects == original.projects


def test_render_failure_after_replacing_artifacts_restores_transaction(saved_cv, monkeypatch):
    client, slug, folder, original, _ = saved_cv
    for name in ('resume.pdf', 'resume.docx'):
        (folder/name).write_bytes(b'original artifact')
    before = {name: (folder/name).read_bytes() for name in ('resume.json','metadata.json','resume.pdf','resume.docx')}
    def fail(*args, **kwargs):
        (folder/'resume.json').write_text('partially written')
        raise ValueError('Save failed after render')
    monkeypatch.setattr(app.state.storage, 'save_current_resume', fail)
    response = client.post(f'/edit/{slug}', data=form_for(client, original, core_skills='Python'), follow_redirects=False)
    assert response.status_code == 422
    assert {name: (folder/name).read_bytes() for name in before} == before


def test_changed_project_claim_requires_its_own_valid_source_references(saved_cv):
    _, _, _, original, job = saved_cv
    original.projects[0].source_fact_ids = ['project:missing:fact:missing']
    original.projects[0].description = 'A saved legacy project description.'
    edited = apply_resume_edits(original, {'project_0_description': app.state.profile.projects[0].description})
    result = FactValidator(app.state.profile, app.state.skills_bank).validate_manual_edit(original, edited, job)
    assert any(issue['field'] == 'project_0_description' for issue in result.issues)
    removed = apply_resume_edits(original, {'project_0_description': '', 'project_0_technologies': ''})
    omission = FactValidator(app.state.profile, app.state.skills_bank).validate_manual_edit(original, removed, job)
    assert not omission.issues and omission.warnings


def test_retained_inflated_legacy_skill_is_flagged_without_approving_it(saved_cv):
    _, _, _, original, job = saved_cv
    original.core_skills = ['Advanced Python', 'Playwright browser automation']
    edited = apply_resume_edits(original, {'core_skills': 'Advanced Python'})
    result = FactValidator(app.state.profile, app.state.skills_bank).validate_manual_edit(original, edited, job)
    assert not result.issues
    assert any('Advanced Python' in warning for warning in result.warnings)
    assert result.resume.selected_skill_ids == []


def test_deletion_does_not_normalize_retained_legacy_labels(resume_payload):
    original = TailoredResume.model_validate(resume_payload)
    original.core_skills = [' Python ', 'Git, GitHub', 'Playwright browser automation']
    edited = apply_resume_edits(original, {'core_skills': ' Python \nGit, GitHub'})
    assert edited.core_skills == original.core_skills[:2]
