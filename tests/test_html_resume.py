"""Synthetic regression coverage for offline exports and saved-record boundaries."""

from html.parser import HTMLParser
from io import BytesIO
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from weasyprint import HTML

from app.main import app
from app.models.resume import TailoredResume
from app.services.html_resume import CSS_PATH, html_resume_zip, render_html_resume
from app.services.resume_export import validate_layout
from tests.test_recording_demo import sign_in


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.text = []
        self.tags = []

    def handle_data(self, data):
        self.text.append(data)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


def test_escaping_and_exact_facts_are_preserved(profile, resume_payload):
    resume = TailoredResume.model_validate(resume_payload)
    resume.professional_summary = 'Personal experiment only; not production. <script>alert("x")</script> & Łódź.'
    resume.experience[0].bullets[0].text = 'Verified <tag> & "quoted" statement; no RSA experience.'
    resume.projects = []
    profile.personal.name = 'Żaneta <img src=x onerror=alert(1)>'
    before, profile_before = resume.model_dump(), profile.model_dump()
    html = render_html_resume(resume, profile)
    parser = TextParser()
    parser.feed(html)
    assert 'script' not in parser.tags and 'img' not in parser.tags
    assert resume.professional_summary in parser.text
    assert resume.experience[0].bullets[0].text in parser.text
    assert profile.personal.name in parser.text
    assert '&lt;script&gt;' in html and '&amp;' in html
    assert resume.model_dump() == before and profile.model_dump() == profile_before
    assert 'experience:0:fact:0' not in html


def test_zip_and_single_file_are_offline_and_have_identical_text(profile, resume_payload):
    resume = TailoredResume.model_validate(resume_payload)
    single = render_html_resume(resume, profile)
    with ZipFile(BytesIO(html_resume_zip(resume, profile, 'candidate-support.html'))) as archive:
        assert set(archive.namelist()) == {'candidate-support.html', 'style.css'}
        external = archive.read('candidate-support.html').decode('utf-8')
        assert 'href="style.css"' in external
        assert archive.read('style.css') == CSS_PATH.read_bytes()
    assert '<style>' in single and '<link' not in single
    assert '<script' not in single and '@import' not in single
    for source in (single, external):
        parser = TextParser()
        parser.feed(source)
        assert resume.professional_summary in parser.text
        assert resume.experience[0].bullets[0].text in parser.text
    with pytest.raises(ValueError):
        html_resume_zip(resume, profile, '../escape.html')


def test_pdf_text_links_and_graceful_pagination(profile, resume_payload):
    profile.personal.name = 'Żaneta Łęcka'
    profile.personal.website = 'https://example.com/project'
    resume = TailoredResume.model_validate(resume_payload)
    resume.experience *= 25
    document = HTML(string=render_html_resume(resume, profile)).render()
    validate_layout(document)
    reader = PdfReader(BytesIO(document.write_pdf()))
    assert len(reader.pages) > 1
    text = '\n'.join(page.extract_text() for page in reader.pages)
    assert 'Żaneta Łęcka' in text
    assert text.count('Invented Kubernetes achievement') == 25  # no silent fact filtering/rewrite
    targets = {str(a.get_object().get('/A', {}).get('/URI', ''))
               for page in reader.pages for a in page.get('/Annots', [])}
    assert profile.personal.website in targets
    assert all(abs(float(p.mediabox.width) - 595.28) < 1 for p in reader.pages)


@pytest.mark.parametrize('kind', ['html', 'zip'])
def test_saved_download_access_review_and_no_mutation(synthetic_download, kind):
    with TestClient(app) as client:
        assert client.get(f'/download/saved/{kind}', follow_redirects=False).status_code == 401
        assert client.get('/html-preview/saved', follow_redirects=False).status_code in {303, 401}
        sign_in(client)
        synthetic_download(app, 'saved', b'%PDF synthetic')
        state = app.state
        folder = state.storage.application_folder('saved')
        paths = list(folder.iterdir()) + [state.settings.data_dir / 'master_profile.json']
        original = {p: p.read_bytes() for p in paths if p.is_file()}
        result = client.get(f'/download/saved/{kind}')
        assert result.status_code == 200, result.text
        assert 'attachment;' in result.headers['content-disposition']
        assert result.headers['content-disposition'].endswith(f'.{kind}"')
        assert result.headers['cache-control'] == 'no-store'
        preview = client.get('/html-preview/saved')
        assert preview.status_code == 200 and '<style>' in preview.text
        assert 'content-disposition' not in preview.headers
        assert all(p.read_bytes() == data for p, data in original.items())
        assert set(folder.iterdir()) == set(p for p in paths if p.parent == folder)
        _, resume, _, _ = state.storage.load_application('saved')
        resume.professional_summary = 'Unreviewed change to the saved summary.'
        (folder / 'resume.json').write_text(resume.model_dump_json(), encoding='utf-8')
        assert client.get(f'/download/saved/{kind}').status_code == 409
        assert client.get('/html-preview/saved').status_code == 409
        assert client.get(f'/download/missing/{kind}').status_code == 404


def test_sections_exclusions_and_unsafe_project_url(profile, resume_payload):
    from app.models.resume import ResumeProject
    resume = TailoredResume.model_validate(resume_payload)
    resume.excluded_sections = ['skills']
    assert '<h2>Core Skills</h2>' not in render_html_resume(resume, profile)
    resume.projects = [ResumeProject(name='Personal project', description='Test',
                                    url='javascript:alert(1)', source_fact_ids=['project:0'])]
    with pytest.raises(ValueError, match='HTTP'):
        render_html_resume(resume, profile)


def test_browser_opens_both_html_formats_without_server(tmp_path, profile, resume_payload):
    from playwright.sync_api import sync_playwright

    resume = TailoredResume.model_validate(resume_payload)
    standalone = tmp_path / 'standalone.html'
    standalone.write_text(render_html_resume(resume, profile), encoding='utf-8')
    extracted = tmp_path / 'editable'
    with ZipFile(BytesIO(html_resume_zip(resume, profile, 'candidate-support.html'))) as archive:
        archive.extractall(extracted)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 375, 'height': 812})
        remote_requests = []

        def block_remote(route):
            remote_requests.append(route.request.url)
            route.abort()

        page.route('http://**/*', block_remote)
        page.route('https://**/*', block_remote)
        for path in (standalone, extracted / 'candidate-support.html'):
            page.goto(path.as_uri())
            assert page.locator('h1').inner_text() == profile.personal.name
            assert page.evaluate('document.characterSet') == 'UTF-8'
            assert page.locator('main').evaluate('(el) => getComputedStyle(el).backgroundColor') == 'rgb(255, 255, 255)'
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            assert page.locator('script').count() == 0
            page.emulate_media(media='print')
            assert page.locator('main').evaluate('(el) => getComputedStyle(el).paddingTop') == '0px'
            page.emulate_media(media='screen')
        assert not remote_requests
        browser.close()
