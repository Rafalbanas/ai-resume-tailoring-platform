from io import BytesIO

import pytest
from docx import Document
from docx.shared import Mm
from pypdf import PdfReader

from app.services.processing import decoded, process
from app.services.text_cv_export import text_cv_export_op, validate_text

TEXT = 'Ada Example\nada@example.test\n\nExperience:\nEXAMPLE LTD | Support Engineer | 2022–Present\nSQL troubleshooting.\nEducation\nBSc | 2021\n'


@pytest.mark.parametrize('text', ['', '   ', 'a' * 60001, 'Invalid\x00content'])
def test_invalid_text_is_rejected(text):
    with pytest.raises(ValueError):
        validate_text(text)


@pytest.mark.parametrize('kind', ['pdf', 'docx'])
@pytest.mark.parametrize('template', ['ats_classic', 'modern_sidebar'])
def test_text_export_preserves_content_without_duplicate_headings(kind, template):
    result = text_cv_export_op({'text': TEXT, 'kind': kind, 'template': template})
    assert isinstance(result, str)
    output = decoded(result)
    if kind == 'pdf':
        reader = PdfReader(BytesIO(output))
        content = '\n'.join(p.extract_text() for p in reader.pages)
        assert abs(float(reader.pages[0].mediabox.width) - 595.28) < 1
        assert abs(float(reader.pages[0].mediabox.height) - 841.89) < 1
    else:
        document = Document(BytesIO(output))
        content = '\n'.join(p.text for p in document.paragraphs)
        assert document.styles['Normal'].font.bold is False
        assert document.styles['Normal'].font.name == 'Arial'
        assert document.styles['Normal'].font.size.pt == 10.5
        assert abs(document.sections[0].page_width - Mm(210)) < Mm(0.1)
        assert abs(document.sections[0].page_height - Mm(297)) < Mm(0.1)
    for value in ['Ada Example', 'ada@example.test', '2022', 'Present', '2021', 'SQL troubleshooting.', 'EXAMPLE LTD']:
        assert value in content
    assert content.count('Experience:') == 1
    assert content.count('Education') == 1
    assert 'Header / unclassified' not in content
    assert '\\n' not in content


def test_pdf_text_is_escaped_and_never_fetches_user_resources():
    text = '<script>alert("xss")</script>\n<img src="https://example.invalid/private">\n'
    output = decoded(text_cv_export_op({'text': text, 'kind': 'pdf', 'template': 'ats_classic'}))
    content = '\n'.join(p.extract_text() for p in PdfReader(BytesIO(output)).pages)
    assert '<script>alert("xss")</script>' in content
    assert '<img src="https://example.invalid/private">' in content


@pytest.mark.parametrize('kind,template', [('invalid', 'ats_classic'), ('pdf', 'invalid')])
def test_invalid_export_options(kind, template):
    with pytest.raises(ValueError):
        text_cv_export_op({'text': TEXT, 'kind': kind, 'template': template})


@pytest.mark.parametrize('kind', ['pdf', 'docx'])
def test_text_export_runs_in_existing_network_isolated_processor(kind):
    result = decoded(process('text_cv_export', {'text': TEXT, 'kind': kind, 'template': 'ats_classic'}))
    assert result.startswith(b'%PDF-' if kind == 'pdf' else b'PK')
