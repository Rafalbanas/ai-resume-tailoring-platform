"""Render fictional short, medium and long CVs; capture both themes and geometry."""
import argparse
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from docx import Document
from PIL import Image, ImageDraw
from pypdf import PdfReader

from app.models.candidate import Experience, Interest
from app.services.analysis_validator import AnalysisValidator
from app.services.docx_generator import _generate_docx_local
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import contacts, prepare_resume
from scripts.compare_resume_quality import bullet_texts, export_and_check, scenario
from scripts.compare_resume_themes import pdf_images
from scripts.resume_quality_scenarios import profile, sparse_draft


def pagination_case(size):
    candidate = profile()
    candidate.personal.website = 'https://example.com/portfolio'
    candidate.personal.linkedin = 'https://www.linkedin.com/in/fictional-ops'
    candidate.skills['languages'] = ['English B2', 'Polish Native']
    candidate.interests = [Interest(id='synthetic-hobby', name='Cycling')]
    candidate.projects[0].url = 'https://example.com/projects/container-lab'
    candidate.projects[1].url = 'https://example.com/projects/calendar-connector'
    if size != 'short':
        # Realistic lengths, dated employers and distinct outcomes. Keep the
        # benchmark's existing evidence as the lead role for all three cases.
        for i in range(1, 6 if size == 'medium' else 9):
            candidate.experience.append(Experience(
                company=f'Example Regional Services {i}', title='Infrastructure Support Specialist',
                start=str(2019 - 2 * i), end=str(2021 - 2 * i), facts=[
                    f'Restored VPN access for {31 + i * 3} users after a client update, '
                    'tracing connection failures with endpoint logs and documenting the rollback procedure.',
                    f'Monitored remote access and Windows Server services across {i + 2} sites '
                    'and escalated recurring VPN incidents with a reproducible diagnosis.',
                    f'Documented workstation recovery for {41 + i * 2} users across two offices '
                    'and verified access before handing the service back to local IT.',
                ],
            ))
    job, analysis = scenario('Technical Support Engineer', candidate)
    # Exercise varied same-page blocks as well as employment. Projects remain
    # source-backed; this stress target explicitly values a homelab.
    job = job.model_copy(update={'job_description': job.job_description.replace(
        'Requirements\n', 'Test container health checks and VPN connectivity in a Linux environment.\nRequirements\n')})
    analysis = AnalysisValidator(candidate).validate(analysis, job.job_description, semantic=False)
    validator = FactValidator(candidate, analysis=analysis)
    resume = prepare_resume(validator.validate(sparse_draft(candidate), job).resume, candidate)
    return candidate, job, validator, resume


def sample_photo(generator):
    generator.photo_store.directory.mkdir(exist_ok=True)
    portrait = Image.new('RGB', (160, 160), '#476783')
    draw = ImageDraw.Draw(portrait)
    draw.ellipse((51, 26, 109, 84), fill='#dce7ed')
    draw.ellipse((32, 90, 128, 183), fill='#dce7ed')
    portrait.save(generator.photo_store.jpg_path)
    return generator.photo_store.jpg_path


def normalized(text):
    return re.sub(r'\s+', '', text).casefold()


def render_cases(output):
    report = {}
    for size in ('short', 'medium', 'long'):
        candidate, job, validator, resume = pagination_case(size)
        report[size] = {}
        for theme in ('modern_sidebar', 'ats_classic'):
            folder = output / size / theme
            folder.mkdir(parents=True, exist_ok=True)
            generator = PDFGenerator(Path('templates'), Path('static'), folder, isolated=False)
            photo = sample_photo(generator)
            guide = {}
            fitted, warnings = generator.fit_resume(resume, candidate, guide,
                template_name=theme, job_text=f'{job.role}\n{job.relevance_text}',
                prefer_one_page=True, fact_validator=validator)
            pages, extracted = export_and_check(generator, folder, 'resume', fitted, candidate, guide, theme)
            if theme == 'modern_sidebar':
                _generate_docx_local(fitted, candidate, folder / 'resume.docx',
                                     photo_path=photo, photo_enabled=True, template_name=theme)
            doc = generator._render_document(generator.render_html(fitted, candidate, guide, template_name=theme))
            data = (folder / 'resume.pdf').read_bytes()
            for index, image in enumerate(pdf_images(data), 1):
                image.save(folder / f'page-{index}.png')
            annotations = {str(a.get_object().get('/A', {}).get('/URI', ''))
                           for page in PdfReader(folder / 'resume.pdf').pages for a in page.get('/Annots', [])}
            links = {c.target for c in contacts(candidate) if c.target} | {p.url for p in fitted.projects if p.url}
            html = BeautifulSoup((folder / 'resume.html').read_text(encoding='utf-8'), 'html.parser')
            docx = Document(folder / 'resume.docx')
            expected_text = [c.display for c in contacts(candidate)]
            extracted_text = {
                'pdf': ' '.join(p.extract_text() for p in PdfReader(folder / 'resume.pdf').pages),
                'docx': '\n'.join(p.text for p in docx.paragraphs),
                'html': html.get_text(' ', strip=True),
            }
            report[size][theme] = {
                'pages': pages, 'geometry': [round(m['height'] / m['available_height'], 3)
                                            for m in generator.page_content_metrics(doc)],
                'experience_bullets': len(bullet_texts(fitted)), 'before_fit': len(bullet_texts(resume)),
                'projects': [p.name for p in fitted.projects], 'fragments': extracted,
                'links_retained': {
                    'pdf': links <= annotations,
                    'docx': links <= {r.target_ref for r in docx.part.rels.values() if r.is_external},
                    'html': links <= {link['href'] for link in html.select('a[href]')},
                },
                'contacts_extractable': {ext: all(normalized(c) in normalized(text) for c in expected_text)
                                         for ext, text in extracted_text.items()},
                'warnings': warnings,
            }
    (output / 'report.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(render_cases(args.output), indent=2))
