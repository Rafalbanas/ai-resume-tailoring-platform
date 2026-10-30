"""Content-preserving text layouts shared by preview and sandboxed exports."""

import base64
from html import escape
from io import BytesIO

from app.services.cv_editor import split_sections, validate_text

SIDEBAR_HEADINGS = {
    'contact', 'contact details', 'skills', 'technical skills', 'core skills',
    'core competencies', 'key skills', 'technical competencies', 'languages', 'interests',
    'umiejętności', 'języki', 'zainteresowania',
}


def section_parts(text):
    for section in split_sections(text):
        lines = section['text'].splitlines(keepends=True)
        heading = section['title'] != 'Header / unclassified content'
        yield (lines[0].strip(), ''.join(lines[1:])) if heading else ('', section['text'])


def is_sidebar(title):
    return title.strip().rstrip(':').casefold() in SIDEBAR_HEADINGS


def render_text_html(text: str, template: str) -> str:
    """No inferred facts, remote resources, truncation or content-based shrinking."""
    validate_text(text)
    if template not in {'ats_classic', 'modern_sidebar'}:
        raise ValueError('Choose an existing CV template.')
    side, main = [], []
    for title, content in section_parts(text):
        heading = f'<h2>{escape(title)}</h2>' if title else ''
        lines = content.splitlines()
        if not title and template == 'modern_sidebar' and lines:
            body = f'<header><h1>{escape(lines[0])}</h1>'
            body += ''.join(f'<p>{escape(line)}</p>' for line in lines[1:] if line.strip()) + '</header>'
        else:
            body = ''.join(f'<p>{escape(line)}</p>' if line.strip() else '<div class="gap"></div>' for line in lines)
        block = f'<section>{heading}{body}</section>'
        (side if template == 'modern_sidebar' and is_sidebar(title) else main).append(block)
    css = '''
        @page { size: A4; margin: 14mm; }
        * { box-sizing: border-box; }
        body { font-family: 'Liberation Sans', Arial, sans-serif; font-size: 10.5pt;
               line-height: 1.25; margin: 0; color: #183049; overflow-wrap: anywhere; }
        p { white-space: pre-wrap; margin: 0 0 2.4px; orphans: 2; widows: 2; }
        h2 { font-size: 12pt; margin: 10pt 0 4pt; break-after: avoid; }
        .gap { height: 1.2mm; }
    '''
    if template == 'modern_sidebar':
        css += '''
        @page { margin: 12mm 0;
            background: linear-gradient(to right, #112e4b 0, #112e4b 62mm, white 62mm, white 100%); }
        body { font-size: 8.7pt; line-height: 1.31; }
        .page { display: grid; grid-template-columns: 62mm 148mm; align-items: start; }
        aside { padding: 0 7.5mm 0 8mm; color: #eff7fc; font-size: 8pt; }
        main { padding: 0 11.7mm; }
        section { margin-bottom: 3mm; }
        aside section { margin-bottom: 8mm; }
        h1 { font-size: 24pt; line-height: 1.05; color: #112e4b; margin: 0 0 3mm; }
        header { border-bottom: 2.2px solid #1d5681; padding-bottom: 3mm; margin-bottom: 4mm; }
        h2 { color: #19496f; font-size: 9pt; letter-spacing: .6px; text-transform: uppercase;
             border-bottom: 1px solid #b7c8d5; padding-bottom: 4px; margin: 0 0 7px; }
        aside h2 { color: #f3f9ff; font-size: 9.1pt; border-color: #7896ad; }
        aside p { margin-bottom: 4px; }
        '''
        content = '<div class="page"><aside>' + ''.join(side) + '</aside><main>' + ''.join(main) + '</main></div>'
    else:
        content = '<main>' + ''.join(main) + '</main>'
    return '<!doctype html><html lang="en"><head><meta charset="utf-8"><style>' + css + '</style></head><body>' + content + '</body></html>'


def export_to_pdf(text: str, template: str) -> bytes:
    from weasyprint import HTML

    def no_resources(url, **kwargs):
        raise ValueError('External resources are not supported in text CV exports.')

    return HTML(string=render_text_html(text, template), url_fetcher=no_resources).write_pdf()


def export_to_docx(text: str, template: str) -> bytes:
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Mm, Pt, RGBColor

    document = Document()
    page = document.sections[0]
    page.page_width, page.page_height = Mm(210), Mm(297)
    page.top_margin = page.bottom_margin = page.left_margin = page.right_margin = Mm(14)
    normal = document.styles['Normal']
    normal.font.name, normal.font.size, normal.font.bold = 'Arial', Pt(10.5), False
    normal.paragraph_format.space_after = Pt(3)
    normal.paragraph_format.line_spacing = 1.15
    heading = document.styles['Heading 1']
    heading.font.name, heading.font.size = 'Arial', Pt(12)
    containers = None
    if template == 'modern_sidebar':
        page.left_margin = page.right_margin = Mm(0)
        page.top_margin = page.bottom_margin = Mm(12)
        table = document.add_table(rows=1, cols=2)
        table.autofit = False
        table.columns[0].width, table.columns[1].width = Mm(62), Mm(148)
        containers = table.rows[0].cells
        for cell, width, left, right in [(containers[0], 62, 8, 7.5), (containers[1], 148, 11.7, 11.7)]:
            cell.width = Mm(width)
            cell.paragraphs[0].paragraph_format.line_spacing = Pt(1)
            cell.paragraphs[0].paragraph_format.space_after = Pt(0)
            margins = OxmlElement('w:tcMar')
            for edge, value in [('start', left), ('end', right)]:
                element = OxmlElement(f'w:{edge}')
                element.set(qn('w:w'), str(int(Mm(value).twips)))
                element.set(qn('w:type'), 'dxa')
                margins.append(element)
            cell._tc.get_or_add_tcPr().append(margins)
        shading = OxmlElement('w:shd')
        shading.set(qn('w:fill'), '112E4B')
        containers[0]._tc.get_or_add_tcPr().append(shading)
    for title, content in section_parts(text):
        side = template == 'modern_sidebar' and is_sidebar(title)
        target = containers[0 if side else 1] if containers else document
        if title:
            paragraph = target.add_paragraph(title, style='Heading 1')
            if containers:
                paragraph.paragraph_format.space_before = Pt(7)
                paragraph.paragraph_format.space_after = Pt(4)
                for run in paragraph.runs:
                    run.font.size = Pt(9.1 if side else 9)
                    run.font.color.rgb = RGBColor.from_string('F3F9FF' if side else '19496F')
        for index, line in enumerate(content.splitlines()):
            paragraph = target.add_paragraph(line)
            if containers:
                paragraph.paragraph_format.space_after = Pt(2.4 if line.strip() else 1)
                paragraph.paragraph_format.line_spacing = 1.28
                if not line.strip():
                    paragraph.paragraph_format.line_spacing = Pt(2)
                for run in paragraph.runs:
                    run.font.size = Pt(8 if side else 8.7)
                    run.font.color.rgb = RGBColor.from_string('EFF7FC' if side else '183049')
                    if not title and index == 0:
                        run.font.size, run.font.bold = Pt(24), True
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def text_cv_export_op(payload: dict) -> str:
    text = validate_text(payload.get('text'))
    kind, template = payload.get('kind'), payload.get('template', 'ats_classic')
    if kind not in {'pdf', 'docx'} or template not in {'ats_classic', 'modern_sidebar'}:
        raise ValueError('Choose PDF/DOCX and an existing CV template.')
    content = export_to_pdf(text, template) if kind == 'pdf' else export_to_docx(text, template)
    return base64.b64encode(content).decode('ascii')
