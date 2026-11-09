from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright

from tests.test_job_form_ui import job_page as _job_page

job_page = _job_page


@pytest.mark.parametrize('action,path', [('fetch-job', '/api/extract-job-url'), ('clean-job-text', '/api/clean-job-text')])
@pytest.mark.parametrize('manual', [None, '200 PLN/h', ''])
def test_salary_autofill_preserves_manual_input(job_page, action, path, manual):
    page, errors = job_page
    page.locator('#job-url').fill('https://example.com/job')
    field = page.locator('#salary-range')
    if manual is not None:
        field.fill('100 PLN/h')
        field.fill(manual)
    page.route('**' + path, lambda route: route.fulfill(json={
        'company': 'Synthetic', 'role': 'Support', 'job_description': 'Verified Python support workflows. ' * 4,
        'extraction_method': 'html', 'salary_range': '100–150 PLN/h B2B'}))
    page.locator('#' + action).click()
    expect(page.locator('#fetch-status')).to_have_class('fetch-status success')
    expect(field).to_have_value('100–150 PLN/h B2B' if manual is None else manual)
    page.locator('#cv-workflow').select_option('custom')
    expect(field).to_be_hidden()
    assert not errors


@pytest.mark.parametrize('width', [375, 1120])
def test_salary_editor_keyboard_and_narrow_layout(width, tmp_path):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    salary = env.get_template('_offer_salary.html').render(
        salary_value='10 000–15 000 PLN netto + VAT / miesiąc · B2B',
        salary_action='/offers/draft/synthetic/salary', csrf_token='synthetic')
    html = '<html><head><style>' + Path('static/app.css').read_text() + '</style></head>'
    html += '<body><main class="shell"><article class="history-row"><div><strong>Synthetic offer</strong>'
    html += salary + '</div><div class="history-meta">HIGH</div><div class="row-actions">Preview</div></article></main></body></html>'
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_content(html)
        page.get_by_text('Edit salary / Edytuj widełki', exact=True).focus()
        page.keyboard.press('Enter')
        field = page.get_by_label('Salary range / Widełki')
        expect(field).to_be_visible()
        page.keyboard.press('Tab')
        expect(field).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / f'offer-salary-{width}.png'))
        page.locator('body').evaluate("node => node.style.zoom = '2'")
        expect(page.get_by_role('button', name='Save salary')).to_be_visible()
        browser.close()
