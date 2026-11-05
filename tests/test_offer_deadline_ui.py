"""Deadline autofill and manual override in the real form JavaScript."""
from datetime import date
from pathlib import Path

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright

from app.services.offer_dates import offer_deadline_view
from tests.test_job_form_ui import job_page as _job_page

job_page = _job_page


@pytest.mark.parametrize('action,path', [('fetch-job', '/api/extract-job-url'), ('clean-job-text', '/api/clean-job-text')])
@pytest.mark.parametrize('manual', [None, '2026-12-15', ''])
def test_deadline_autofill_never_overwrites_manual_changes(job_page, action, path, manual):
    page, errors = job_page
    page.locator('#job-url').fill('https://example.com/job')
    field = page.get_by_label('Offer valid until')
    if manual is not None:
        field.fill('2026-12-01')
        field.fill(manual)
    page.route('**' + path, lambda route: route.fulfill(json={
        'company': 'Synthetic', 'role': 'Support', 'job_description': 'Verified Python support workflows. ' * 4,
        'extraction_method': 'html', 'offer_valid_until': '2026-11-30'}))
    page.locator('#' + action).click()
    expect(page.locator('#fetch-status')).to_have_class('fetch-status success')
    expect(field).to_have_value('2026-11-30' if manual is None else manual)
    assert not errors


def test_deadline_edit_during_fetch_is_preserved(job_page):
    page, errors = job_page
    page.locator('#job-url').fill('https://example.com/job')
    pending = []
    page.route('**/api/extract-job-url', lambda route: pending.append(route))
    page.locator('#fetch-job').click()
    expect(page.locator('#fetch-job')).to_be_disabled()
    page.locator('#offer-valid-until').fill('2026-12-15')
    assert len(pending) == 1
    pending[0].fulfill(json={'company': 'Synthetic', 'role': 'Support',
                            'job_description': 'Support Python workflows. ' * 4,
                            'extraction_method': 'html', 'offer_valid_until': '2026-11-30'})
    expect(page.locator('#fetch-job')).to_be_enabled()
    expect(page.locator('#offer-valid-until')).to_have_value('2026-12-15')
    assert not errors


def test_deadline_hides_for_custom_workflow_and_has_keyboard_label(job_page):
    page, errors = job_page
    field = page.get_by_label('Offer valid until')
    expect(field).to_be_visible()
    field.focus()
    expect(field).to_be_focused()
    page.locator('#cv-workflow').select_option('custom')
    expect(field).to_be_hidden()
    page.locator('#cv-workflow').select_option('job')
    expect(field).to_be_visible()
    assert not errors


@pytest.mark.parametrize('width', [375, 1120])
def test_deadline_editor_keyboard_and_narrow_layout(width, tmp_path):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    deadline = env.get_template('_offer_deadline.html').render(
        deadline_value='2000-01-01', deadline_action='/offers/draft/synthetic/deadline', csrf_token='synthetic',
        offer_deadline_view=lambda value: offer_deadline_view(value, today=date(2026, 11, 4)))
    html = '<html><head><style>' + Path('static/app.css').read_text() + '</style></head>'
    html += '<body><main class="shell"><article class="history-row"><div><strong>Synthetic offer</strong>'
    html += deadline + '</div><div class="history-meta">HIGH</div><div class="row-actions">Preview</div></article></main></body></html>'
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_content(html)
        summary = page.get_by_text('Edit offer deadline', exact=True)
        summary.focus()
        page.keyboard.press('Enter')
        expect(page.get_by_label('Offer valid until')).to_be_visible()
        page.keyboard.press('Tab')
        expect(page.get_by_label('Offer valid until')).to_be_focused()
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.screenshot(path=str(tmp_path / f'offer-deadline-{width}.png'))
        page.locator('body').evaluate("node => node.style.zoom = '2'")
        expect(page.get_by_role('button', name='Save deadline')).to_be_visible()
        browser.close()
