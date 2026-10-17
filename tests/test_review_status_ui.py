from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import sync_playwright


@pytest.mark.parametrize("width", [360, 768, 1280])
def test_review_statuses_wrap_and_limited_keeps_downloads(width):
    env = Environment(loader=FileSystemLoader("templates"), autoescape=select_autoescape(["html"]))
    metadata = {
        "company": "Example company",
        "role": "Technical Support Engineer for Application Integration and Infrastructure Operations",
        "match_level": "LIMITED",
        "recommendation": "REVIEW",
        "provider_used": "ollama",
        "model_used": "qwen3.5:9b",
        "analysis_reliable": False,
        "document_status": "layout_and_exports_checked",
        "candidate_data_status": "export fields checked",
        "template_name": "ats_classic",
    }
    html = env.get_template("resume_preview.html").render(
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)),
        metadata=metadata,
        slug="fixture",
        asset_version="test",
        resume_html="<p>Verified CV preview</p>",
        photo_available=False,
        csrf_token="fixture",
        pre_fit_diff=None,
    )
    css = Path("static/app.css").read_text()
    html = html.replace("</head>", f"<style>{css}</style></head>")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": width, "height": 900})
            page.route("**/*", lambda route: route.fulfill(status=200, body=""))
            page.set_content(html)
            assert page.locator(".review-statuses").is_visible()
            assert page.get_by_text("Layout and exports checked", exact=False).is_visible()
            assert page.get_by_text("Source review required", exact=False).is_visible()
            assert page.get_by_role("link", name="Download PDF").is_visible()
            assert page.get_by_role("link", name="Download DOCX").is_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            for selector in [".review-statuses", ".provider-meta", ".preview-head h1"]:
                assert page.locator(selector).evaluate(
                    "(el)=>{const a=el.getBoundingClientRect(); const b=el.parentElement.getBoundingClientRect();return a.left>=b.left-1 && a.right<=b.right+1}"
                )
        finally:
            browser.close()


@pytest.mark.parametrize('width,zoom', [(360, 1), (768, 1), (1280, 1), (1280, 2)])
def test_summary_confirmation_is_accessible_and_wraps(width, zoom):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    review = {'text': 'I automate Python workflows for support teams.', 'sources': [
        SimpleNamespace(text='Automates repeatable support workflows with Python.', owner_name='Profile')],
        'required': True, 'confirmed': False, 'source_text': False, 'model_reviewed': True, 'token': 'synthetic-token'}
    if width == 360:
        review['text'] += '<script>window.injected=true</script><input type="checkbox" name="summary_confirmed" checked>'
    html = env.get_template('resume_preview.html').render(
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)),
        metadata={'company': 'Synthetic', 'role': 'Python support', 'match_level': 'MEDIUM', 'recommendation': 'REVIEW'},
        slug='synthetic', asset_version='test', resume_html='<p>CV preview</p>', photo_available=False,
        csrf_token='synthetic', pre_fit_diff=None, summary_review=review)
    html = html.replace('</head>', '<style>' + Path('static/app.css').read_text() + '</style></head>')
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={'width': width, 'height': 1000})
            page.route('**/*', lambda route: route.fulfill(status=200, body=''))
            page.set_content(html)
            page.evaluate('(zoom) => document.body.style.zoom = zoom', zoom)
            form = page.locator('form[action$="/summary/confirm"]')
            assert form.locator('input[name=summary_confirmed]').count() == 1
            assert page.evaluate('window.injected') is None
            assert not form.evaluate('(form) => form.checkValidity()')
            checkbox = page.get_by_role('checkbox', name='I reviewed this summary and confirm that its claims are accurate.')
            checkbox.focus()
            checkbox.press('Space')
            assert checkbox.is_checked()
            assert form.evaluate('(form) => form.checkValidity()')
            assert page.get_by_text('Reviewed by AI. Your confirmation is still required.').is_visible()
            assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
            if width == 1280 and zoom == 1:
                page.screenshot(path='/tmp/cvtailor-summary-confirmation.png', full_page=True)
        finally:
            browser.close()
