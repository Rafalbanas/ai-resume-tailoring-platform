"""Synthetic reference-shape regressions; no private CV fixtures or live services."""
import shutil
import subprocess
from io import BytesIO
from pathlib import Path

import pytest
from docx import Document
from docx.oxml.ns import qn
from PIL import Image, ImageChops, ImageStat
from pypdf import PdfReader
from weasyprint import HTML

from app.services.text_cv_export import export_to_docx, export_to_pdf, render_text_html

FIXTURES = Path(__file__).parent / 'fixtures'
SAMPLE = (FIXTURES / 'modern_sidebar.txt').read_text()


def test_modern_pdf_has_reference_columns_one_page_and_all_content():
    rendered = HTML(string=render_text_html(SAMPLE, 'modern_sidebar')).render()
    assert len(rendered.pages) == 1
    boxes = [box for box in rendered.pages[0]._page_box.descendants() if type(box).__name__ == 'BlockBox']
    sidebar = next(box for box in boxes if box.element_tag == 'aside')
    main = next(box for box in boxes if box.element_tag == 'main')
    assert sidebar.position_x == pytest.approx(0, abs=1)
    assert main.position_x == pytest.approx(62 * 96 / 25.4, abs=1)
    reader = PdfReader(BytesIO(export_to_pdf(SAMPLE, 'modern_sidebar')))
    text = reader.pages[0].extract_text().casefold()
    for line in SAMPLE.splitlines():
        # PDF line wrapping does not change words or discard sections.
        assert ''.join(line.casefold().split()) in ''.join(text.split())


def test_long_sidebar_and_main_paginate_without_lost_content():
    text = ('Ada Example\nCore Skills\n' + '\n'.join(f'Skill {i} verified' for i in range(180))
            + '\nExperience\n' + '\n'.join(f'Incident {i} resolved.' for i in range(200)))
    reader = PdfReader(BytesIO(export_to_pdf(text, 'modern_sidebar')))
    assert len(reader.pages) > 1
    content = ' '.join(page.extract_text() for page in reader.pages)
    for i in range(180):
        assert f'Skill {i} verified' in content
    for i in range(200):
        assert f'Incident {i} resolved.' in content


def test_modern_docx_uses_real_fixed_width_colored_sidebar():
    document = Document(BytesIO(export_to_docx(SAMPLE, 'modern_sidebar')))
    assert len(document.tables) == 1
    table = document.tables[0]
    assert table.autofit is False
    assert table.columns[0].width.mm == pytest.approx(62, abs=.1)
    assert table.columns[1].width.mm == pytest.approx(148, abs=.1)
    side, main = table.rows[0].cells
    assert side._tc.tcPr.find(qn('w:shd')).get(qn('w:fill')) == '112E4B'
    assert 'Core Skills' in side.text and 'Experience' not in side.text
    assert 'Experience' in main.text and 'Core Skills' not in main.text
    for line in SAMPLE.splitlines():
        assert line in side.text + main.text


def test_reference_selected_projects_heading_remains_a_separate_section():
    from bs4 import BeautifulSoup

    text = SAMPLE.replace('\nProjects\n', '\nSelected Projects · Personal\n')
    soup = BeautifulSoup(render_text_html(text, 'modern_sidebar'), 'html.parser')
    assert any(heading.get_text() == 'Selected Projects · Personal' for heading in soup.select('main h2'))


@pytest.mark.skipif(not shutil.which('pdftoppm'), reason='Poppler needed for raster visual regression')
def test_modern_pdf_visual_baseline(tmp_path):
    pdf = tmp_path / 'modern.pdf'
    pdf.write_bytes(export_to_pdf(SAMPLE, 'modern_sidebar'))
    subprocess.run(['pdftoppm', '-scale-to', '1100', '-png', '-singlefile', str(pdf), str(tmp_path / 'actual')],
                   check=True, capture_output=True, timeout=30)
    actual = Image.open(tmp_path / 'actual.png').convert('RGB')
    expected = Image.open(FIXTURES / 'modern_sidebar.png').convert('RGB')
    assert actual.size == expected.size
    # Tolerate raster/font antialiasing, not changed columns, spacing or content.
    difference = ImageChops.difference(actual, expected)
    assert max(ImageStat.Stat(difference).mean) < 2
    y = actual.height // 2
    assert actual.getpixel((10, y)) == (17, 46, 75)
    assert actual.getpixel((int(actual.width * 62 / 210) + 2, y)) == (255, 255, 255)


@pytest.mark.skipif(not shutil.which('libreoffice'), reason='LibreOffice needed for DOCX pagination check')
def test_reference_shaped_docx_converts_to_one_page(tmp_path):
    docx = tmp_path / 'modern.docx'
    docx.write_bytes(export_to_docx(SAMPLE, 'modern_sidebar'))
    subprocess.run(['libreoffice', f'-env:UserInstallation={(tmp_path / "lo-profile").as_uri()}',
                    '--headless', '--convert-to', 'pdf', '--outdir', str(tmp_path), str(docx)],
                   check=True, capture_output=True, timeout=60)
    reader = PdfReader(tmp_path / 'modern.pdf')
    assert len(reader.pages) == 1
    assert 'GDPR' in reader.pages[0].extract_text()
