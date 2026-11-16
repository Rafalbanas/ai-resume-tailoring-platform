import pytest
from weasyprint import HTML

from app.services.pdf_generator import PDFGenerator


def test_paragraph_fragments_are_joined_without_repeated_page_furniture():
    text = " ".join(f"Documented technical action {i}." for i in range(120))
    document = HTML(string=f"""
        <style>@page {{ size:120mm 100mm; margin:10mm; }}
        body {{ font:11pt Arial; }} footer {{ position:fixed; bottom:0; }}</style>
        <footer>Repeated page furniture.</footer>
        <section><h2>Project</h2><p>{text}</p></section>
    """).render()
    assert len(document.pages) > 1
    PDFGenerator._validate_rendered_sources(document)


def test_duplicate_visible_text_cannot_hide_a_missing_source_node():
    document = HTML(string="""
        <section><p>Distinct supported achievement.</p>
        <p style="display:none">Distinct supported achievement.</p></section>
    """).render()
    with pytest.raises(ValueError, match="omitted during pagination"):
        PDFGenerator._validate_rendered_sources(document)


def test_nested_links_and_inline_fragments_belong_to_their_source_paragraph():
    document = HTML(string="""
        <section><p>Built a <strong>Python</strong> project;
        <a href="https://example.org">documented methods</a> and results.</p></section>
    """).render()
    PDFGenerator._validate_rendered_sources(document)
