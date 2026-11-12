"""The HTML format must retain the chosen PDF theme, facts and links."""
import base64
import re
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pytest
from bs4 import BeautifulSoup
from PIL import Image
from pypdf import PdfReader

from app.services.docx_generator import generate_docx
from app.services.html_resume import html_resume_zip, render_html_resume
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import contacts
from scripts.compare_resume_themes import fictional_data


def normalized(value):
    return re.sub(r'\s+', '', value)


@pytest.fixture
def renderer(tmp_path):
    return PDFGenerator(Path('templates'), Path('static'), tmp_path, isolated=False)


@pytest.mark.parametrize('theme', ['modern_sidebar', 'ats_classic'])
def test_actual_theme_full_facts_links_and_shared_css(renderer, theme):
    profile, resume = fictional_data()
    before = (profile.model_dump(), resume.model_dump())
    options = dict(generator=renderer, template_name=theme, photo_enabled=False)
    markup = render_html_resume(resume, profile, **options)
    soup = BeautifulSoup(markup, 'html.parser')
    assert bool(soup.select('aside.resume-sidebar')) == (theme == 'modern_sidebar')
    assert soup.select_one('article.' + theme.replace('_', '-'))
    assert Path('static/resume.css').read_text() in soup.style.get_text()
    if theme == 'modern_sidebar':
        assert soup.select_one('aside .contact-block')
        for heading in ('Skills', 'Languages'):
            assert soup.select_one('aside').find('h2', string=heading)
    else:
        assert soup.select_one('.ats-contact')
        assert soup.find('h2', string='Core Skills')
    text = normalized(soup.body.get_text(' ', strip=True))
    values = [profile.personal.name, resume.headline, resume.professional_summary, *resume.core_skills,
              *resume.interests, 'Cloud fundamentals', 'Learning in progress', 'English B2', 'Polish Native']
    for experience in resume.experience:
        values.extend([experience.title, experience.company, experience.dates, *[b.text for b in experience.bullets]])
    for education in resume.education:
        values.extend([education.institution, education.qualification, education.dates,
                       education.specialisation, education.thesis_subline])
    for project in resume.projects:
        values.extend([project.name, project.description, *project.technologies])
    for certification in resume.certifications:
        values.extend([certification.name, certification.issuer, certification.date])
    assert all(normalized(value) in text for value in values)
    targets = {a['href'] for a in soup.select('a[href]')}
    for contact in contacts(profile):
        assert normalized(contact.display) in text
        if contact.target:
            assert contact.target in targets
    assert resume.projects[0].url in targets
    assert not soup.select('script, [data-cfemail], .__cf_email__')
    assert not any(bad in markup for bad in ('/cdn-cgi/', 'beacon.min.js', 'email-decode.min.js'))
    assert '<!--email_off-->' in markup and '<!--/email_off-->' in markup
    assert (profile.model_dump(), resume.model_dump()) == before
    with ZipFile(BytesIO(html_resume_zip(resume, profile, **options))) as archive:
        assert set(archive.namelist()) == {'index.html', 'style.css'}
        external = BeautifulSoup(archive.read('index.html'), 'html.parser')
        assert str(external.body) == str(soup.body)
        assert external.select_one('link[rel=stylesheet]')['href'] == 'style.css'
        assert archive.read('style.css').decode('utf-8') == soup.style.get_text()


@pytest.mark.parametrize('theme', ['modern_sidebar', 'ats_classic'])
def test_embedded_photo_respects_chosen_theme_and_preference(renderer, theme):
    profile, resume = fictional_data()
    renderer.photo_store.directory.mkdir(parents=True)
    Image.new('RGB', (100, 100), '#43688a').save(renderer.photo_store.jpg_path)
    original = renderer.photo_store.jpg_path.read_bytes()
    for enabled in (False, True):
        soup = BeautifulSoup(render_html_resume(resume, profile, generator=renderer,
            template_name=theme, photo_enabled=enabled), 'html.parser')
        images = soup.select('img')
        assert bool(images) == (enabled and theme == 'modern_sidebar')
        if images:
            assert base64.b64decode(images[0]['src'].split(',', 1)[1]) == original
            assert images[0]['alt'] == 'Profile photo'


@pytest.mark.parametrize('theme', ['modern_sidebar', 'ats_classic'])
def test_page_fragments_do_not_drop_or_rewrite_long_bullet(renderer, theme):
    profile, resume = fictional_data()
    # Isolate a flowing paragraph rather than constructing a nearly empty tail
    # of unrelated sections (the existing PDF renderer intentionally rejects it).
    resume.education = []
    resume.projects = []
    resume.certifications = []
    resume.currently_learning = []
    resume.interests = []
    statement = ('Verified local support workflow; not a commercial deployment. ' * 180).rstrip()
    resume.experience[0].bullets = [resume.experience[0].bullets[0].model_copy(update={'text': statement})]
    markup = render_html_resume(resume, profile, generator=renderer, template_name=theme, photo_enabled=False)
    soup = BeautifulSoup(markup, 'html.parser')
    assert len(soup.select('.resume-paper')) > 1
    actual = ''.join(li.get_text() for li in soup.select('.entry ul li'))
    assert normalized(actual) == normalized(statement)
    assert len(soup.select('.consent-footer')) == 1
    assert resume.experience[0].bullets[0].text == statement


@pytest.mark.parametrize('theme', ['modern_sidebar', 'ats_classic'])
def test_original_pdf_and_docx_exports_still_work(renderer, tmp_path, theme):
    profile, resume = fictional_data()
    pdf, docx = tmp_path / 'resume.pdf', tmp_path / 'resume.docx'
    renderer.generate(resume, profile, pdf, template_name=theme, photo_enabled=False)
    generate_docx(resume, profile, docx, template_name=theme, photo_enabled=False)
    text = ' '.join(page.extract_text() for page in PdfReader(pdf).pages)
    assert normalized(profile.personal.name).casefold() in normalized(text).casefold()
    assert normalized(resume.professional_summary) in normalized(text)
    with ZipFile(docx) as archive:
        xml = archive.read('word/document.xml').decode('utf-8')
        relationships = archive.read('word/_rels/document.xml.rels').decode('utf-8')
        assert profile.personal.name in xml
        assert 'mailto:' + str(profile.personal.email) in relationships


def test_large_floated_sidebar_remains_complete_in_html(renderer, profile, resume_payload):
    from tests.test_sidebar_pagination import long_resume

    resume = long_resume(resume_payload)
    soup = BeautifulSoup(render_html_resume(resume, profile, generator=renderer,
        template_name='modern_sidebar', photo_enabled=False), 'html.parser')
    assert len(soup.select('.resume-paper')) > 1
    skills = [item.get_text() for item in soup.select('aside .skill-list li')]
    assert skills == resume.core_skills
    assert soup.body.get_text().count('Fact 0:') == len(resume.experience)
    assert len(soup.select('.consent-footer')) == 1
