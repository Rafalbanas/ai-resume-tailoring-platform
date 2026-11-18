"""Visual and cross-format regressions using the real renderers and fictional facts."""
from io import BytesIO
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from docx import Document
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from app.services.docx_generator import _generate_docx_local
from app.services.html_resume import render_html_resume
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import contacts, validate_layout
from scripts.compare_modern_pagination import pagination_case, sample_photo
from scripts.compare_resume_themes import check_browser_text_layout, pdf_images


@pytest.mark.parametrize('size, expected_pages', [('short', 1), ('medium', 2), ('long', 2)])
def test_modern_retains_validated_content_and_visual_identity(tmp_path, size, expected_pages):
    candidate, job, validator, resume = pagination_case(size)
    generator = PDFGenerator(Path('templates'), Path('static'), tmp_path, isolated=False)
    sample_photo(generator)
    guide = {}
    fitted, _ = generator.fit_resume(resume, candidate, guide, template_name='modern_sidebar',
        job_text=f'{job.role}\n{job.relevance_text}', prefer_one_page=True, fact_validator=validator)
    assert fitted == resume
    assert not guide  # No one-page content or font changes.
    document = generator._render_document(generator.render_html(fitted, candidate))
    validate_layout(document)
    assert len(document.pages) == expected_pages
    body_metrics = generator.page_content_metrics(document)
    if expected_pages == 2:
        assert all(m['height'] / m['available_height'] >= .43 for m in body_metrics)
    pdf = document.write_pdf(pdf_tags=True)
    pages = PdfReader(BytesIO(pdf)).pages
    for index, (image, rendered, pdf_page) in enumerate(zip(pdf_images(pdf), document.pages, pages, strict=True)):
        # Sample the real raster independently of the style attributes.
        assert image.getpixel((12, image.height // 2)) == (16, 43, 70)
        assert image.getpixel((image.width - 8, image.height // 2)) == (255, 255, 255)
        text = pdf_page.extract_text()
        targets = {str(a.get_object().get('/A', {}).get('/URI', '')) for a in pdf_page.get('/Annots', [])}
        assert ('CONTINUED' in text) == bool(index)
        assert f'mailto:{candidate.personal.email}' in targets
        assert ('GDPR' in text) == (index == expected_pages - 1)
        boxes = list(rendered._page_box.descendants())
        # PDF pages can share an XObject dictionary even when the portrait is
        # not drawn there. Inspect placed boxes, not the resource inventory.
        assert len({b.element for b in boxes if b.element_tag == 'img'}) == (1 if index == 0 else 0)
        main = next(b for b in boxes if type(b).__name__ == 'BlockBox' and b.element_tag == 'main')
        for section in (b for b in main.descendants() if type(b).__name__ == 'BlockBox' and b.element_tag == 'section'):
            tags = {b.element_tag for b in section.descendants() if type(b).__name__ == 'TextBox'}
            assert 'h2' not in tags or tags & {'h3', 'p', 'li', 'a'}
        owners = [box for box in boxes if type(box).__name__ == 'BlockBox' and box.element is not None
                  and 'experience-entry' in box.element.get('class', '').split()]
        for owner in owners:
            # In these fixtures every role fits on one page: do not leave a
            # heading stranded or break a short job entry mid-bullet-list.
            assert any(box.element_tag == 'h3' and type(box).__name__ == 'TextBox' for box in owner.descendants())
            bullets = [box for box in owner.descendants() if box.element_tag == 'li' and type(box).__name__ == 'TextBox']
            assert {box.element for box in bullets} == set(owner.element.findall('ul/li'))
            assert all(box.style['font_size'] == pytest.approx(10 * 96 / 72) for box in bullets)


def test_modern_offline_browser_and_simplified_docx_hold_page_two_content(tmp_path):
    candidate, _, _, resume = pagination_case('medium')
    generator = PDFGenerator(Path('templates'), Path('static'), tmp_path, isolated=False)
    photo = sample_photo(generator)
    html_file = tmp_path / 'resume.html'
    html_file.write_text(render_html_resume(resume, candidate, generator=generator), encoding='utf-8')
    html = BeautifulSoup(html_file.read_text(encoding='utf-8'), 'html.parser')
    assert len(html.select('.resume-paper')) == 2
    assert len(html.select('img[alt="Profile photo"]')) == 1
    assert html.select_one('[data-page="2"] .resume-continuation a')['href'] == f'mailto:{candidate.personal.email}'
    assert html.select_one('[data-page="2"] .project-entry a')['href'] == resume.projects[0].url
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        page = browser.new_page(viewport={'width': 1000, 'height': 1200}, java_script_enabled=False)
        requests = []

        def block_external(route):
            requests.append(route.request.url)
            route.abort()

        page.route('http*/**', block_external)
        page.goto(html_file.as_uri())
        assert check_browser_text_layout(page) > 100
        continuation = page.locator('[data-page="2"] .resume-continuation')
        assert continuation.is_visible() and continuation.locator('a').is_visible()
        # Rendering the semantic HTML as A4 must not create a third blank
        # page or drop the continuation link.
        printed = PdfReader(BytesIO(page.pdf(prefer_css_page_size=True, print_background=True)))
        assert len(printed.pages) == 2
        assert 'CONTINUED' in printed.pages[1].extract_text()
        assert resume.projects[0].name in printed.pages[1].extract_text()
        assert not requests
        browser.close()

    output = tmp_path / 'resume.docx'
    _generate_docx_local(resume, candidate, output, template_name='modern_sidebar',
                         photo_path=photo, photo_enabled=True)
    docx = Document(output)
    assert len(docx.inline_shapes) == 1
    assert not docx.tables
    expected_links = {c.target for c in contacts(candidate) if c.target} | {p.url for p in resume.projects}
    assert expected_links <= {r.target_ref for r in docx.part.rels.values() if r.is_external}
    paragraphs = '\n'.join(p.text for p in docx.paragraphs)
    assert all(b.text in paragraphs for owner in resume.experience for b in owner.bullets)
    assert all(p.description in paragraphs for p in resume.projects)
    kept = {paragraph.text: paragraph.paragraph_format.keep_with_next for paragraph in docx.paragraphs
            if paragraph.style.name == 'List Bullet'}
    for owner in resume.experience:
        assert all(kept[b.text] for b in owner.bullets[:-1])
        assert kept[owner.bullets[-1].text] is False


def test_modern_standard_export_does_not_probe_for_content_removal(monkeypatch, tmp_path):
    candidate, job, validator, resume = pagination_case('medium')
    generator = PDFGenerator(Path('templates'), Path('static'), tmp_path, isolated=False)
    def unexpected(*args, **kwargs):
        pytest.fail('Modern should not look for a one-page subset of the validated CV.')
    monkeypatch.setattr(generator, '_fits_one_page', unexpected)
    fitted, warnings = generator.fit_resume(resume, candidate, {'compact_headings': True},
        template_name='modern_sidebar', prefer_one_page=True, fact_validator=validator, job_text=job.relevance_text)
    assert fitted == resume and not warnings
