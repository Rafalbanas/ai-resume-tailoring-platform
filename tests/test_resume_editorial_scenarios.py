"""Fictional A–D cases; no provider calls or saved candidate documents."""
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from app.models.candidate import CandidateProfile, Experience, Project
from app.models.job import JobRequest
from app.models.resume import ResumeBullet, ResumeExperience, TailoredResume
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.docx_generator import generate_docx
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator
from app.services.professional_summary import build_summary, summary_contains_clause
from app.services.skills_bank import SkillsBank


def scenario(case):
    title, role, facts, project_facts, terms = {
        'A': ('Technical Support Engineer', 'DevOps Engineer', [
            'Documents customer support requests.',
            'Monitors Linux services and investigates system logs.',
            'Automates Linux service checks using Bash.'], [
                'Deployed a Docker application on Linux in a personal lab.',
                'Tested container networking in a personal lab.'], 'Linux Docker Kubernetes CI/CD Bash monitoring'),
        'B': ('IT Administrator', 'System Administrator', [
            'Documents equipment inventory.',
            'Administers Windows servers and Active Directory.',
            'Tested backup restoration for Windows servers.'], [
                'Configured Linux virtual machines in a personal lab.'], 'Windows Linux Active Directory backup'),
        'C': ('Application Support Engineer', 'Production Support Engineer', [
            'Documents customer support requests.',
            'Troubleshoots application incidents using SQL queries and API logs.',
            'Analyzes application logs for incident investigation.'], [
                'Built a Python tool for reading API logs in a personal project.'], 'SQL API logs incidents troubleshooting'),
        'D': ('Support Assistant', 'Software Engineer', [
            'Documents customer support requests.'], [
                'Built a Python API in a personal project.',
                'Tested API endpoints using pytest in a personal project.',
                'Plans to add Kubernetes deployment.'], 'Python API tests Git'),
    }[case]
    profile = CandidateProfile(personal={'name': 'Synthetic Candidate'},
        summary_facts=['Administers Linux services in a personal lab.'] if case == 'A' else [],
        experience=[Experience(company='Example Operations', title=title, start='2024', end='Present', facts=facts),
                    Experience(company='Earlier Example', title='Office Assistant', start='2022', end='2023',
                               facts=['Maintained office records.'])],
        projects=[Project(name='Personal lab', facts=project_facts, url='https://example.org/lab')])
    job = JobRequest(company='Synthetic Target', role=role, job_description='Requirements\n' + terms)
    catalog = FactCatalog(profile)
    # Reverse the useful duties deliberately: model order is not a quality guarantee.
    entries = [e for e in catalog.prompt_entries if e.kind == 'experience' and e.owner_index == 0 and ':fact:' in e.source_id]
    draft = TailoredResume(headline=role, professional_summary='Unsupported expert.', core_skills=[],
        experience=[ResumeExperience(company=profile.experience[0].company, title=title, dates='2024 – Present',
            bullets=[ResumeBullet(text=e.text, source_fact_ids=[e.source_id]) for e in entries])])
    return profile, job, draft


@pytest.mark.parametrize('case', list('ABCD'))
def test_synthetic_editorial_scenarios(case):
    profile, job, draft = scenario(case)
    original = profile.model_dump()
    validator = FactValidator(profile, review_key='synthetic-key')
    result = validator.validate(draft, job).resume
    assert profile.model_dump() == original
    assert [e.title for e in result.experience] == [e.title for e in profile.experience]
    assert [e.company for e in result.experience] == [e.company for e in profile.experience]
    assert result.headline == profile.experience[0].title
    assert 'Unsupported expert' not in result.professional_summary
    assert result.professional_summary.endswith('.')
    assert 'Background: Administers' not in result.professional_summary
    assert len(result.professional_summary) <= 700
    if case in 'ABC':
        assert result.experience[0].bullets[0].text != profile.experience[0].facts[0]
    for experience in result.experience:
        for bullet in experience.bullets:
            entries = validator.catalog.valid(bullet.source_fact_ids)
            assert entries
            assert all(e.kind == 'experience' and profile.experience[e.owner_index].company == experience.company for e in entries)
    assert result.projects[0].url == profile.projects[0].url
    if case == 'D':
        assert 'Project work' in result.professional_summary
        assert 'personal project' in result.professional_summary
        assert 'Plans to add Kubernetes' not in result.professional_summary
        assert not summary_contains_clause(result.professional_summary, result.projects[0].description)
    again = validator.validate(result, job).resume
    assert again.professional_summary == result.professional_summary
    assert again.experience == result.experience


def test_identity_does_not_consume_the_only_relevant_employment_fact():
    profile, job, _ = scenario('A')
    profile.summary_facts = []
    profile.projects = []
    profile.experience[0].facts = ['Automates Linux service checks using Bash.']
    text, ids = build_summary(FactCatalog(profile), job.role + '\n' + job.relevance_text)
    assert 'Automates Linux service checks using Bash.' in text
    assert text.startswith('Technical Support Engineer at Example Operations.')
    assert ids


def test_administration_background_uses_a_natural_scoped_clause():
    profile, job, _ = scenario('B')
    profile.summary_facts = ['Administers Linux services in a personal lab.']
    profile.experience[0].facts = ['Documents equipment inventory.']
    profile.projects = []
    text, ids = build_summary(FactCatalog(profile), job.role)
    assert 'Broader experience includes administering Linux services in a personal lab.' in text
    assert 'Background:' not in text
    assert ids


def test_support_identity_keeps_its_first_diagnostic_duty_available():
    profile, job, _ = scenario('C')
    profile.experience[0].facts = [profile.experience[0].facts[1]]
    text, _ = build_summary(FactCatalog(profile), job.role)
    assert 'Troubleshoots application incidents using SQL queries and API logs.' in text


def test_relevant_experience_is_not_displaced_by_an_equally_relevant_project():
    profile, job, _ = scenario('D')
    profile.experience[0].facts = ['Built a Python API for an internal application.']
    profile.projects[0].facts = ['Built a Python API in a personal project.']
    text, _ = build_summary(FactCatalog(profile), job.role + '\n' + job.relevance_text)
    assert 'internal application' in text
    assert text.index('internal application') < text.index('Project work')


def test_source_order_endpoint_and_manual_bullets_are_not_reordered():
    profile, job, draft = scenario('A')
    job.tailoring_level = 1
    result = FactValidator(profile).validate(draft, job).resume
    assert [b.text for b in result.experience[0].bullets] == profile.experience[0].facts
    job.tailoring_level = 0
    manual = FactValidator(profile).validate(draft, job, preserve_skills=True).resume
    assert [b.text for b in manual.experience[0].bullets] == profile.experience[0].facts


def test_unrelated_basic_skills_do_not_pad_a_stronger_relevant_list(tmp_path):
    profile, job, draft = scenario('A')
    skills = [VerifiedSkill(id=f'skill_synthetic_{i}', name=name, category='Tools', level=level,
        verified=True, allowed_in_cv=True, evidence=[SkillEvidence(source_type='manual_verified',
            source_id=f'manual:synthetic:{i}', description='Synthetic verification.')])
        for i, (name, level) in enumerate([('Linux', 'hands_on'), ('Docker', 'basic'),
            ('Kubernetes', 'learning'), ('Photo editing', 'basic'), ('Office macros', 'basic')])
        if level != 'learning']
    path = tmp_path / 'skills.json'
    path.write_text(SkillsDocument(skills=skills).model_dump_json())
    bank = SkillsBank(path, profile)
    result = FactValidator(profile, bank).validate(draft, job).resume
    assert result.core_skills == ['Linux', 'Basic Docker']
    assert 'Kubernetes' not in result.core_skills
    manual = bank.select_for_job([skills[-1].id], job.role, requested_only=True, minimum=0)
    assert [s.id for s in manual] == [skills[-1].id]


@pytest.mark.parametrize('case', list('ABCD'))
def test_synthetic_cases_export_without_losing_history_or_project_scope(tmp_path, case):
    profile, job, draft = scenario(case)
    profile.personal.email = 'synthetic@example.com'
    resume = FactValidator(profile).validate(draft, job).resume
    generator = PDFGenerator(Path('templates'), Path('static'), tmp_path)
    html = generator.render_html(resume, profile, template_name='ats_classic')
    pdf, docx = tmp_path / 'cv.pdf', tmp_path / 'cv.docx'
    generator.generate(resume, profile, pdf, template_name='ats_classic')
    generate_docx(resume, profile, docx, template_name='ats_classic')
    pdf_text = ' '.join(page.extract_text() for page in PdfReader(pdf).pages)
    docx_text = ' '.join(p.text for p in Document(docx).paragraphs)
    for text in (html, pdf_text, docx_text):
        assert profile.experience[0].title in text
        assert 'Earlier Example' in text
        assert 'Office Assistant' in text
        assert 'Personal lab' in text
        assert 'personal' in text.lower()
        assert 'Unsupported expert' not in text
