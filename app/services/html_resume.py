"""Portable exports of the existing PDF themes, not an alternative CV design."""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
from xml.etree import ElementTree
from zipfile import ZIP_DEFLATED, ZipFile

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[2]
CSS_PATH = ROOT / 'static' / 'resume.css'


def _fragments(document):
    """Partition source DOM at the PDF engine's existing page boundaries.

    Most elements are copied verbatim. Only text nodes spanning pages are split,
    by their measured character counts, retaining original case/whitespace/facts.
    This is semantic editable HTML, not glyph positioning or page screenshots.
    """
    members, by_page = {}, []
    for index, page in enumerate(document.pages):
        boxes = {}
        for box in page._page_box.descendants():
            element = getattr(box, 'element', None)
            if element is None or '::' in str(getattr(box, 'element_tag', '')):
                continue
            boxes.setdefault(element, []).append(box)
            members.setdefault(element, set()).add(index)
        by_page.append(boxes)

    def fragment(element, index):
        pages = members.get(element, set())
        if index not in pages:
            return None
        if pages == {index}:
            return deepcopy(element)
        node = ElementTree.Element(element.tag, element.attrib)
        source = element.text or ''
        if source.strip():
            # Plain summary/description/bullet paragraphs can span pages. Match
            # measured text to the source rather than copying transformed text.
            chunks = {i: ''.join(b.text for b in by_page[i].get(element, []) if type(b).__name__ == 'TextBox')
                      for i in sorted(pages)}
            positions = [i for i, char in enumerate(source) if not char.isspace()]
            def compact(text):
                return ''.join(c for c in text if not c.isspace())
            if compact(source) != ''.join(compact(text) for text in chunks.values()):
                raise ValueError('Cannot preserve source text across HTML page boundaries.')
            start = sum(len(compact(chunks[i])) for i in pages if i < index)
            end = start + len(compact(chunks[index]))
            start = positions[start] if start else 0
            end = positions[end] if end < len(positions) else len(source)
            node.text = source[start:end]
        else:
            node.text = source
        for child in element:
            copied = fragment(child, index)
            if copied is not None:
                copied.tail = child.tail if index == max(members[child]) else None
                node.append(copied)
        return node

    return by_page, fragment


def _position(box):
    """Use measured page/column geometry, not a second set of theme dimensions."""
    values = {'position': 'absolute', 'float': 'none', 'margin': '0',
              'left': f'{box.border_box_x()}px', 'top': f'{box.border_box_y()}px',
              'width': f'{box.border_width()}px'}
    for side in ('top', 'right', 'bottom', 'left'):
        values[f'padding-{side}'] = f'{getattr(box, "padding_" + side)}px'
    return ';'.join(f'{key}:{value}' for key, value in values.items())


def offline_assets(markup, template_name, document):
    """Adapt only page furniture unsupported by browsers; retain editable text.

    Input is trusted Jinja output from the shared PDF renderer, never scraped
    HTML or a CDN response. Candidate content has already been escaped.
    """
    soup = BeautifulSoup(markup, 'html.parser')
    soup.html['class'] = ['offline-resume', f'theme-{template_name.replace("_", "-")}']
    viewport = soup.new_tag('meta', attrs={'name': 'viewport', 'content': 'width=device-width, initial-scale=1'})
    soup.head.append(viewport)
    # Cloudflare email obfuscation must not replace visible addresses/mailto links.
    from bs4 import Comment
    # Browsers lack running elements and have different fragmentation semantics.
    # Reuse WeasyPrint's source fragments and measured column positions per A4
    # page, while all typography, colors and content still use resume.html/CSS.
    pages, fragment = _fragments(document)
    soup.body.clear()
    for index, boxes in enumerate(pages):
        def block(class_name, boxes=boxes):
            return next((b for el, values in boxes.items() if class_name in el.get('class', '').split()
                         for b in values if type(b).__name__ == 'BlockBox'), None)

        article_box = block('resume-document')
        article = BeautifulSoup(ElementTree.tostring(fragment(article_box.element, index), encoding='unicode', method='html'), 'html.parser').article
        paper = soup.new_tag('div', attrs={'class': 'resume-paper', 'data-page': str(index + 1),
                                         'aria-label': f'CV page {index + 1} of {len(pages)}'})
        paper.append(article)
        for name in ('resume-main', 'resume-sidebar'):
            source_box = block(name)
            node = article.select_one('.' + name)
            if source_box is not None and node is not None:
                node['style'] = _position(source_box)
        footer = block('consent-footer')
        if footer is not None:
            node = BeautifulSoup(ElementTree.tostring(footer.element, encoding='unicode', method='html'), 'html.parser').footer
            node['style'] = _position(footer)
            paper.append(node)
        if index and template_name == 'modern_sidebar':
            header = soup.new_tag('div', attrs={'class': 'resume-running-header'})
            # The original running-header text is page furniture, not a new fact.
            from weasyprint.formatting_structure.boxes import MarginBox
            for box in document.pages[index]._page_box.descendants():
                if isinstance(box, MarginBox) and box.at_keyword == '@top-right':
                    header.string = ''.join(b.text for b in box.descendants() if type(b).__name__ == 'TextBox')
            paper.append(header)
        soup.body.append(paper)
    for contact in soup.select('.contact-block, .ats-contact'):
        contact.insert_before(Comment('email_off'))
        contact.insert_after(Comment('/email_off'))
    css = '\n'.join(style.get_text() for style in soup.select('head style'))
    css += '\n' + (ROOT / 'static' / 'resume-browser.css').read_text(encoding='utf-8')
    for style in soup.select('head style'):
        style.decompose()
    return {'markup': str(soup), 'css': css}


def _assets(resume, profile, *, generator=None, template_name='modern_sidebar', layout_guide=None,
            photo_enabled=None):
    if generator is None:
        from app.services.pdf_generator import PDFGenerator
        generator = PDFGenerator(ROOT / 'templates', ROOT / 'static')
    return generator.export_html_assets(resume, profile, layout_guide,
        template_name=template_name, photo_enabled=photo_enabled)


def _document(assets, external_css):
    soup = BeautifulSoup(assets['markup'], 'html.parser')
    if external_css:
        soup.head.append(soup.new_tag('link', rel='stylesheet', href='style.css'))
    else:
        style = soup.new_tag('style')
        style.string = assets['css']
        soup.head.append(style)
    return str(soup)


def render_html_resume(resume, profile, *, external_css=False, **options):
    """Caller enforces saved-record access/review; worker retains PDF safeguards."""
    return _document(_assets(resume, profile, **options), external_css)


def html_resume_zip(resume, profile, document_name='index.html', **options):
    """Fixed relative members; legacy name argument accepted but never used as a path."""
    if Path(document_name).name != document_name or '/' in document_name or '\\' in document_name:
        raise ValueError('Invalid document name')
    assets = _assets(resume, profile, **options)
    output = BytesIO()
    with ZipFile(output, 'w', compression=ZIP_DEFLATED) as archive:
        archive.writestr('index.html', _document(assets, True).encode('utf-8'))
        archive.writestr('style.css', assets['css'].encode('utf-8'))
    return output.getvalue()
