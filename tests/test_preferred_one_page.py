from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

from app.models.job import JobAnalysis, JobRequest
from app.services.fact_validator import FactValidator
from app.services.one_page_resume import prefer_one_page
from scripts.compare_resume_richness import OFFERS, rich_profile, sparse_draft


def sample():
    profile = rich_profile()
    job = JobRequest(company='Synthetic', role='DevOps Engineer',
                     job_description='Requirements\n' + OFFERS['DevOps Engineer'])
    validator = FactValidator(profile)
    resume = validator.validate(sparse_draft(profile), job).resume
    return validator, resume


def test_small_cv_does_not_lose_any_content():
    validator, resume = sample()
    original = deepcopy(resume)
    fitted, warnings = prefer_one_page(resume, validator, 'DevOps Engineer\nLinux Docker', lambda _: True)
    assert fitted == original and not warnings
    assert resume == original


def test_incremental_selection_preserves_full_summary_best_project_and_history():
    validator, resume = sample()
    original = deepcopy(resume)
    initial = sum(len(e.bullets) for e in resume.experience)
    fitted, warnings = prefer_one_page(resume, validator, 'DevOps Engineer\nLinux Docker',
        lambda cv: sum(len(e.bullets) for e in cv.experience) < initial)
    assert warnings
    assert fitted.professional_summary == resume.professional_summary
    assert fitted.summary_source_fact_ids == resume.summary_source_fact_ids
    assert fitted.projects[0] == resume.projects[0]
    assert fitted.education == resume.education
    assert [(e.company, e.title, e.dates) for e in fitted.experience] == [
        (e.company, e.title, e.dates) for e in resume.experience]
    assert all(e.bullets for e in fitted.experience)
    assert resume == original


def test_mandatory_evidence_cannot_be_removed_for_page_count():
    validator, resume = sample()
    protected = {i for e in resume.experience for b in e.bullets for i in b.source_fact_ids}
    validator.analysis = SimpleNamespace(requirements=[
        SimpleNamespace(priority='mandatory', status='strong', source_fact_ids=list(protected))],
        role_competencies=[])
    seen = []
    def fits(cv):
        seen.append(deepcopy(cv))
        return False
    fitted, warnings = prefer_one_page(resume, validator, 'DevOps Engineer\nLinux Docker', fits)
    assert fitted == resume
    assert all(protected <= {i for e in cv.experience for b in e.bullets for i in b.source_fact_ids} for cv in seen)
    assert 'multi-page' in warnings[0]


def test_required_skill_evidence_resolves_legacy_source_ids(tmp_path):
    from app.models.job import JobRequirement
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
    from app.services.skills_bank import SkillsBank

    profile = rich_profile()
    path = tmp_path / "skills.json"
    path.write_text(SkillsDocument(skills=[VerifiedSkill(
        id="skill_python_test", name="Python", category="Tools", level="hands_on",
        verified=True, allowed_in_cv=True, evidence=[SkillEvidence(
            source_type="employment", source_id="experience:0:fact:3",
            description="Attested Python diagnostic automation.")])]).model_dump_json())
    bank = SkillsBank(path, profile)
    job = JobRequest(company="Synthetic", role="DevOps Engineer",
                     job_description="Requirements\nPython automation and Linux.")
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
        missing_requirements=[], recommendation="REVIEW", match_level="LOW", requirements=[
            JobRequirement(name="Python automation", source_quote="Python automation and Linux.",
                           priority="mandatory", status="strong", source_fact_ids=["skill:skill_python_test"])])
    validator = FactValidator(profile, bank, analysis)
    resume = validator.validate(sparse_draft(profile), job).resume
    canonical = validator.catalog.get("experience:0:fact:3").source_id
    assert validator.fact_priorities[canonical] > 0
    seen = []
    def fits(cv):
        ids = {i for e in cv.experience for b in e.bullets for i in b.source_fact_ids}
        seen.append(ids)
        return canonical not in ids
    fitted, _ = prefer_one_page(resume, validator, job.role + "\n" + job.relevance_text, fits)
    assert fitted == resume
    assert seen and all(canonical in ids for ids in seen)


def test_impossible_single_page_falls_back_without_partial_omissions():
    validator, resume = sample()
    fitted, warnings = prefer_one_page(resume, validator, 'DevOps Engineer\nLinux Docker', lambda _: False)
    assert fitted == resume
    assert len(warnings) == 1 and 'important evidence' in warnings[0]


def test_optional_skill_can_be_omitted_without_desynchronizing_ids():
    validator, resume = sample()
    resume.core_skills += ['Unrelated editorial tooling']
    resume.selected_skill_ids = [f'skill_test_{i}' for i in range(len(resume.core_skills))]
    fitted, _ = prefer_one_page(resume, validator, 'DevOps Engineer\n' + ' '.join(resume.core_skills[:-1]),
                               lambda cv: len(cv.core_skills) == 10)
    assert 'Unrelated editorial tooling' not in fitted.core_skills
    assert len(fitted.selected_skill_ids) == len(fitted.core_skills) == 10
    assert fitted.professional_summary == resume.professional_summary


def test_standard_export_requests_soft_preference_not_hard_one_page(monkeypatch, resume_payload):
    from fastapi.testclient import TestClient

    from app.main import app
    from app.models.resume import TailoredResume
    from tests.test_provider_fallback import job, sample_workflow_response
    from tests.test_recording_demo import sign_in

    with TestClient(app) as client:
        sign_in(client)
        response = sample_workflow_response('mock', 'fixture')
        response.resume = TailoredResume.model_validate(resume_payload)
        draft = app.state.storage.save_draft(job(), response)
        def inspect(*args, **kwargs):
            assert kwargs['prefer_one_page'] is True
            assert kwargs['one_page'] is False
            raise ValueError('Synthetic inspection stop.')
        monkeypatch.setattr(app.state.pdf_generator, 'fit_resume', inspect)
        result = client.post(f'/generate/{draft}', data={
            'csrf_token': client.cookies.get('csrf_token'), 'template_name': 'modern_sidebar'},
            follow_redirects=False)
        assert result.status_code == 422
        assert 'Synthetic inspection stop' in result.text


def test_original_profile_endpoint_orders_model_bullets_by_canonical_profile():
    profile = rich_profile()
    job = JobRequest(company='Synthetic', role='DevOps Engineer',
                     job_description='Requirements\n' + OFFERS['DevOps Engineer'], tailoring_level=1)
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation='REVIEW', match_level='LOW')
    validator = FactValidator(profile, analysis=analysis)
    draft = validator.validate(sparse_draft(profile), job).resume
    draft.experience[0].bullets.reverse()
    assert [b.text for b in validator.validate(draft, job).resume.experience[0].bullets] == profile.experience[0].facts[:4]


def test_real_a4_preference_omits_optional_detail_not_summary_or_project(tmp_path):
    from app.models.candidate import Experience
    from app.services.pdf_generator import PDFGenerator
    from app.services.resume_export import validate_layout

    profile = rich_profile()
    profile.experience = [Experience(company=f"Synthetic Operations {i}", title="Support Engineer",
        start=str(2024 - i), end="Present" if i == 0 else str(2025 - i), facts=[
            f"Monitored Linux service group {i}-{j}, investigated diagnostic logs, documented recovery procedures "
            "and escalated network incidents with the operations team using Bash scripts."
            for j in range(4)]) for i in range(3)]
    job = JobRequest(company='Synthetic', role='DevOps Engineer',
                     job_description='Requirements\n' + OFFERS['DevOps Engineer'])
    validator = FactValidator(profile)
    resume = validator.validate(sparse_draft(profile), job).resume
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path, isolated=False)
    original = generator._render_document(generator.render_html(resume, profile, template_name='ats_classic'))
    assert len(original.pages) > 1
    guide = {}
    fitted, warnings = generator.fit_resume(resume, profile, guide, template_name='ats_classic',
        prefer_one_page=True, fact_validator=validator, job_text=job.role + "\n" + job.relevance_text)
    document = generator._render_document(generator.render_html(fitted, profile, guide, template_name='ats_classic'))
    validate_layout(document)
    assert len(document.pages) == 1
    assert fitted.professional_summary == resume.professional_summary
    assert fitted.projects[0] == resume.projects[0]
    assert len(fitted.experience) == len(profile.experience)
    assert all(e.bullets for e in fitted.experience)
    assert warnings
