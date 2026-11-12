"""Generate fictional offline HTML/PDF and browser comparisons; never read a private profile.

Run from the repository root:
    python -m scripts.compare_resume_themes --output /tmp/opencode/resume-theme-previews
Requires the existing development dependencies and Chromium. No server is started.
"""

import argparse
import json
import re
from contextlib import closing
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

import pypdfium2
from PIL import Image, ImageDraw
from playwright.sync_api import sync_playwright
from pypdf import PdfReader

from app.models.candidate import CandidateProfile
from app.models.resume import TailoredResume
from app.services.html_resume import html_resume_zip, render_html_resume
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import validate_layout


def fictional_data(long=False):
    """Identical explicit fictional facts for both themes and all output formats."""
    profile = CandidateProfile.model_validate({
        'personal': {'name': 'Żaneta Testowa', 'email': 'zaneta@example.com',
                     'secondary_email': 'contact@example.com', 'phone': '+48 000 000 000',
                     'location': 'Łódź, Poland', 'website': 'https://example.com/portfolio',
                     'github': 'https://github.com/example'},
        'summary_facts': ['Fictional support engineer using Python for local automation and SQL for data verification.'],
        'skills': {'development': ['Python', 'FastAPI', 'Pydantic', 'SQL', 'Git', 'Docker'],
                   'languages': ['English B2', 'Polish Native']},
        'experience': [], 'education': [], 'projects': [], 'certifications': [],
    })
    experience = [dict(company='Fictional Systems', title='Support Engineer', dates='2023 – Present', bullets=[
        dict(text='Investigated application incidents and escalated documented issues to engineering.',
             source_fact_ids=['experience:0:fact:0']),
        dict(text='Used SQL queries for data verification; automated selected tasks with Python.',
             source_fact_ids=['experience:0:fact:1'])])]
    if long:
        experience = [dict(experience[0], title=f'Synthetic role {i + 1}', dates=f'{2025 - i} – {2026 - i}')
                      for i in range(16)]
    resume = TailoredResume.model_validate({
        'headline': 'Support Engineer | Python & SQL', 'professional_summary': profile.summary_facts[0],
        'summary_source_fact_ids': ['summary:0'], 'core_skills': profile.skills['development'],
        'experience': experience,
        'education': [dict(institution='Fictional Technical University', qualification='MSc, Computer Science',
                           dates='2023', specialisation='Software Systems', thesis_subline='Local automation research',
                           source_fact_ids=['education:0'])],
        'projects': [dict(name='Local Automation Demo', url='https://example.com/demo',
                          description='Personal Python/FastAPI experiment with source references; not a commercial deployment.',
                          technologies=['Python', 'FastAPI', 'Pydantic'], source_fact_ids=['project:0'])],
        'certifications': [dict(name='Synthetic Training Completion', issuer='Example Academy', date='2025')],
        'currently_learning': [dict(skill_id='synthetic', name='Cloud fundamentals', status='Learning in progress')],
        'interests': ['Cycling'],
    })
    return profile, resume


def pdf_images(data):
    images = []
    with closing(pypdfium2.PdfDocument(data)) as document:
        for source in document:
            with closing(source) as page:
                bitmap = page.render(scale=96 / 72)
                try:
                    images.append(bitmap.to_pil().convert('RGB').copy())
                finally:
                    bitmap.close()
    return images


def check_browser_text_layout(page):
    """Check actual browser line rectangles, not estimated character lengths."""
    return page.evaluate('''() => {
      let checked = 0;
      for (const paper of document.querySelectorAll('.resume-paper')) {
        const bounds = paper.getBoundingClientRect();
        const walker = document.createTreeWalker(paper, NodeFilter.SHOW_TEXT);
        const boxes = [];
        while (walker.nextNode()) {
          const node = walker.currentNode;
          if (!node.textContent.trim()) continue;
          const range = document.createRange(); range.selectNodeContents(node);
          for (const rect of range.getClientRects()) {
            if (rect.width < 1 || rect.height < 1) continue;
            if (rect.left < bounds.left - 1 || rect.right > bounds.right + 1 ||
                rect.top < bounds.top - 1 || rect.bottom > bounds.bottom + 1)
              throw new Error('Text outside A4 page: ' + node.textContent.slice(0, 60));
            boxes.push(rect); checked++;
          }
        }
        for (let i = 0; i < boxes.length; i++) {
          for (let j = i + 1; j < boxes.length; j++) {
            const a = boxes[i], b = boxes[j];
            const dx = Math.min(a.right, b.right) - Math.max(a.left, b.left);
            const dy = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
            if (dx > 1.2 && dy > 1.2) throw new Error('Overlapping browser text lines');
          }
        }
      }
      return checked;
    }''')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    root = Path(__file__).resolve().parents[1]
    report = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=['--no-sandbox'])
        for long in (False, True):
            profile, resume = fictional_data(long)
            for theme in ('modern_sidebar', 'ats_classic'):
                label = theme + ('-long' if long else '')
                folder = args.output / label
                folder.mkdir(exist_ok=True)
                generator = PDFGenerator(root / 'templates', root / 'static', folder, isolated=False)
                generator.photo_store.directory.mkdir(exist_ok=True)
                portrait = Image.new('RGB', (200, 200), '#708fa6')
                avatar = ImageDraw.Draw(portrait)
                avatar.ellipse((66, 30, 134, 100), fill='#dce7ed')
                avatar.ellipse((35, 110, 165, 245), fill='#dce7ed')
                portrait.save(generator.photo_store.jpg_path)
                options = dict(generator=generator, template_name=theme, photo_enabled=True)
                html = render_html_resume(resume, profile, **options)
                (folder / 'resume.html').write_text(html, encoding='utf-8')
                archive_data = html_resume_zip(resume, profile, **options)
                (folder / 'resume.zip').write_bytes(archive_data)
                with ZipFile(BytesIO(archive_data)) as archive:
                    archive.extractall(folder / 'editable')
                generator.generate(resume, profile, folder / 'resume.pdf', template_name=theme, photo_enabled=True)
                document = generator._render_document(generator.render_html(resume, profile, template_name=theme,
                                                                            photo_enabled=True))
                validate_layout(document)
                page = browser.new_page(viewport={'width': 1000, 'height': 1200}, device_scale_factor=1)
                requests = []

                def block(route, requests=requests):
                    requests.append(route.request.url)
                    route.abort()

                page.route('http://**/*', block)
                page.route('https://**/*', block)
                page.goto((folder / 'resume.html').resolve().as_uri())
                text_boxes_checked = check_browser_text_layout(page)
                screenshots = []
                for i in range(page.locator('.resume-paper').count()):
                    screenshots.append(page.locator('.resume-paper').nth(i).screenshot(path=str(folder / f'browser-page-{i + 1}.png')))
                (folder / 'browser.png').write_bytes(screenshots[0])
                geometry = {name: page.locator(selector).first.bounding_box()
                            for name, selector in [('paper', '.resume-paper'), ('main', '.resume-main')]}
                if theme == 'modern_sidebar':
                    geometry['sidebar'] = page.locator('.resume-sidebar').first.bounding_box()
                    assert abs(geometry['sidebar']['width'] - 61 * 96 / 25.4) < 1
                    assert abs(geometry['main']['x'] - geometry['paper']['x'] - 61 * 96 / 25.4) < 1
                assert page.get_by_role('link', name=str(profile.personal.email), exact=True).get_attribute('href') == 'mailto:' + str(profile.personal.email)
                browser_pdf = page.pdf(prefer_css_page_size=True, print_background=True, display_header_footer=False)
                (folder / 'browser-print.pdf').write_bytes(browser_pdf)
                # Both download variants must display exactly the same page.
                page.goto((folder / 'editable' / 'index.html').resolve().as_uri())
                for i, expected in enumerate(screenshots):
                    assert page.locator('.resume-paper').nth(i).screenshot() == expected, 'Standalone/ZIP appearance differs'
                assert not requests
                pdf_data = (folder / 'resume.pdf').read_bytes()
                pdf_pages, print_pages = pdf_images(pdf_data), pdf_images(browser_pdf)
                assert len(pdf_pages) == len(print_pages), 'Browser/PDF page counts differ'
                for i, image in enumerate(pdf_pages):
                    image.save(folder / f'pdf-page-{i + 1}.png')
                for i, image in enumerate(print_pages):
                    image.save(folder / f'print-page-{i + 1}.png')
                screenshot = Image.open(folder / 'browser.png').convert('RGB')
                width, height = pdf_pages[0].size
                collage = Image.new('RGB', (width * 3, height + 32), '#dde4ec')
                draw = ImageDraw.Draw(collage)
                for i, (title, image) in enumerate([('HTML: browser', screenshot), ('PDF: WeasyPrint', pdf_pages[0]),
                                                   ('HTML: A4 print', print_pages[0])]):
                    draw.text((i * width + 12, 8), title, fill='#172536')
                    collage.paste(image.crop((0, 0, width, height)), (i * width, 32))
                collage.save(folder / 'comparison.png')
                def norm(value):
                    return re.sub(r'\W+', '', value).casefold()
                pdf_text = norm(' '.join(p.extract_text() for p in PdfReader(BytesIO(pdf_data)).pages))
                print_text = norm(' '.join(p.extract_text() for p in PdfReader(BytesIO(browser_pdf)).pages))
                for data in (pdf_data, browser_pdf):
                    reader = PdfReader(BytesIO(data))
                    assert sum((p.extract_text() or '').count('I consent to the processing') for p in reader.pages) == 1
                for value in [profile.personal.name, str(profile.personal.email), resume.professional_summary,
                              *[b.text for e in resume.experience for b in e.bullets],
                              *[p.description for p in resume.projects]]:
                    assert norm(value) in pdf_text and norm(value) in print_text
                report.append({'theme': theme, 'long': long, 'pdf_pages': len(pdf_pages),
                               'browser_print_pages': len(print_pages), 'geometry': geometry,
                               'standalone_zip_pixels_identical': True, 'all_expected_text_in_both_pdfs': True,
                               'browser_text_boxes_checked': text_boxes_checked,
                               'network_requests': len(requests)})
                print(label, 'PDF pages:', len(pdf_pages), 'browser print:', len(print_pages), flush=True)
                page.close()
        browser.close()
    (args.output / 'results.json').write_text(json.dumps(report, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
