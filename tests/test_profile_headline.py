"""Broader professional profiles must still use whole, verified source labels."""
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.docx_generator import generate_docx
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator


@pytest.mark.parametrize('title,skills,headline', [
    ('Technical Support Engineer (L2)', ['IT Infrastructure'],
     'IT Infrastructure & Technical Support Engineer (L2)'),
    ('IT Administrator', ['Linux administration'], 'Linux administration / IT Administrator'),
    ('Application Support Engineer', ['SQL troubleshooting'], 'Application Support Engineer — SQL troubleshooting'),
    ('Research Assistant', ['Basic Python', 'Data analysis'], 'Basic Python & Data analysis'),
    ('Designer', ['Typography', 'Editorial design'], 'Typography · Editorial design'),
])
def test_whole_attested_labels_can_describe_a_broader_profile(profile, title, skills, headline):
    profile.experience[0].title = title
    profile.skills = {'technical': skills}
    job = JobRequest(company='Synthetic', role='Target Specialist', job_description='Requirements\n' + ' '.join(skills))
    draft = TailoredResume(headline=headline, professional_summary='Needs review.', core_skills=skills, experience=[])
    validator = FactValidator(profile)
    result = validator.validate(draft, job).resume
    assert result.headline == headline
    assert result.experience[0].title == title
    assert validator.validate(result, job).resume.headline == headline
    assert validator.validate(result, job, preserve_skills=True).resume.headline == headline


@pytest.mark.parametrize('headline', [
    'DevOps Engineer', 'Linux Engineer & Support Engineer', 'Advanced Linux & Support Engineer',
    'Linux & Support Engineer', 'Support Engineer — Kubernetes', 'Support Engineer — Basic Linux expert',
])
def test_headline_cannot_create_an_occupation_skill_or_level(profile, headline):
    profile.skills = {'technical': ['Basic Linux']}
    draft = TailoredResume(headline=headline, professional_summary='Needs review.', core_skills=['Basic Linux'], experience=[])
    job = JobRequest(company='Synthetic', role='DevOps Engineer', job_description='Requirements\nLinux and Kubernetes administration.')
    assert FactValidator(profile).validate(draft, job).resume.headline == profile.experience[0].title


def test_headline_revalidates_after_skill_removal(profile):
    profile.skills = {'technical': ['Linux']}
    draft = TailoredResume(headline='Linux & Support Engineer', professional_summary='Needs review.',
                           core_skills=['Linux'], experience=[])
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nLinux administration and troubleshooting.')
    profile.skills = {}
    assert FactValidator(profile).validate(draft, job).resume.headline == 'Support Engineer'


def test_manual_headline_change_uses_the_same_source_boundary(profile):
    profile.skills = {'technical': ['Basic Linux']}
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nLinux administration and troubleshooting.')
    validator = FactValidator(profile)
    original = validator.validate(TailoredResume(headline='Support Engineer', professional_summary='Needs review.',
        core_skills=['Basic Linux'], experience=[]), job).resume
    edited = original.model_copy(update={'headline': 'Support Engineer — Basic Linux'})
    result = validator.validate_manual_edit(original, edited, job)
    assert not any(i['field'] == 'headline' for i in result.issues)
    assert result.resume.headline == edited.headline
    inflated = original.model_copy(update={'headline': 'Support Engineer — Advanced Linux'})
    assert any(i['field'] == 'headline' for i in validator.validate_manual_edit(original, inflated, job).issues)


@pytest.mark.parametrize('layout', ['modern_sidebar', 'ats_classic'])
def test_broader_headline_survives_html_pdf_and_docx(tmp_path, profile, layout):
    profile.skills = {'technical': ['Basic Linux']}
    headline = 'Support Engineer & Basic Linux'
    job = JobRequest(company='Synthetic', role='Engineer', job_description='Requirements\nLinux administration and troubleshooting.')
    resume = FactValidator(profile).validate(TailoredResume(headline=headline, professional_summary='Needs review.',
        core_skills=['Basic Linux'], experience=[]), job).resume
    generator = PDFGenerator(Path('templates'), Path('static'), tmp_path)
    html = generator.render_html(resume, profile, template_name=layout)
    assert 'Support Engineer &amp; Basic Linux' in html
    pdf, docx = tmp_path / 'cv.pdf', tmp_path / 'cv.docx'
    generator.generate(resume, profile, pdf, template_name=layout)
    generate_docx(resume, profile, docx, template_name=layout)
    assert headline in ' '.join(page.extract_text() for page in PdfReader(pdf).pages)
    assert headline in ' '.join(p.text for p in Document(docx).paragraphs)
