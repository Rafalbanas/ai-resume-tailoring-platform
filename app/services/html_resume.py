"""Offline, text-preserving exports of an already saved CV; never update facts."""

from io import BytesIO
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.services.cv_content_policy import check_export_content
from app.services.languages import profile_languages
from app.services.resume_export import contacts, link_display, web_link

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / 'static' / 'resume-offline.css'
SECTION_ORDER = ['summary', 'skills', 'learning', 'languages', 'experience', 'education',
                 'projects', 'certifications', 'interests']


def render_html_resume(resume, profile, *, external_css=False):
    """Escape candidate text without rewriting saved statements.

    Caller enforces saved-record access and summary review, as for PDF/DOCX.
    Evidence IDs remain in the record, not the public CV.
    """
    check_export_content(resume)
    for project in resume.projects:
        if project.url:
            web_link(project.url)
    order = list(dict.fromkeys(resume.section_order + SECTION_ORDER))
    env = Environment(loader=FileSystemLoader(ROOT / 'templates'), autoescape=select_autoescape(['html']))
    return env.get_template('resume_offline.html').render(
        resume=resume, personal=profile.personal, contacts=contacts(profile),
        languages=profile_languages(profile), link_display=link_display,
        web_link=web_link, section_order=[s for s in order if s not in resume.excluded_sections],
        external_css=external_css, css=CSS_PATH.read_text(encoding='utf-8'))


def html_resume_zip(resume, profile, document_name):
    """Only relative archive members; no filesystem paths from users."""
    if Path(document_name).name != document_name or '/' in document_name or '\\' in document_name:
        raise ValueError('Invalid document name')
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr(document_name, render_html_resume(resume, profile, external_css=True).encode('utf-8'))
        archive.writestr('style.css', CSS_PATH.read_bytes())
    return output.getvalue()
