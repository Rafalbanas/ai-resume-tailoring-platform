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
