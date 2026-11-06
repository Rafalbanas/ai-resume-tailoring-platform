"""Real history controls with fictional records, at desktop and mobile widths."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright


def history_html():
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    common = {'role': 'AI Developer', 'date': '2026-11-06', 'workflow': 'job', 'job_url': '',
              'match_level': 'MEDIUM', 'recommendation': 'REVIEW', 'has_pdf': True, 'has_docx': True,
              'history_status': 'completed', 'batch_ids': ['a' * 32], 'batch_labels': [],
              'generation_finished_label': '2026-11-06 12:00:00 UTC'}
    rows = [dict(common, slug='older', company='Zulu', cv_name='Zulu CV', generation_finished_label='2026-11-06 10:00:00 UTC',
                 history_timestamp='2026-11-06T10:00:00Z'),
            dict(common, slug='newer', company='Alpha', cv_name='Alpha CV', recommendation='APPLY',
                 history_timestamp='2026-11-06T12:00:00Z'),
            dict(common, slug='no-files', company='Missing', cv_name='Missing CV', has_pdf=False, has_docx=False,
                 history_status='no_files', history_timestamp='', generation_finished_label='', batch_ids=[])]
    analyses = [dict(company='Draft', role='Support', date='2026-11-06', status='report_ready', interrupted=False,
                     draft_id='b' * 32, view_url='/analysis/' + 'b' * 32, edit_url='/?from_draft=' + 'b' * 32,
                     match_level='LOW', recommendation='RETRY', history_status='review_required',
                     history_timestamp='2026-11-06T11:00:00Z', batch_ids=['a' * 32])]
    html = env.get_template('history.html').render(rows=rows, analyses=analyses, app_root_path='/workspace',
        history_batches=[{'id': 'a' * 32, 'label': 'Synthetic batch'}], asset_version='test',
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), csrf_token='synthetic')
    html = re.sub(r'<script[^>]*src="[^"]+"[^>]*></script>', '', html)
    html = re.sub(r'<link[^>]*>', '', html)
    return html.replace('</head>', '<style>' + Path('static/app.css').read_text() + '</style><script>'
                        + Path('static/history.js').read_text() + '</script></head>')


@pytest.fixture(params=[375, 1280])
def history_page(request):
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': request.param, 'height': 900}, timezone_id='Europe/Warsaw')
        page.set_default_timeout(5000)
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        page.set_content(history_html())
        yield page
        assert not errors
        browser.close()


def test_default_sort_and_downloadable_only(history_page):
    page = history_page
    assert page.locator('[data-entry-type="generated"]').first.get_attribute('data-company') == 'alpha'
    expect(page.locator('#history-filter-count')).to_have_text('Showing 4 of 4 entries')
    page.get_by_role('button', name='Show downloadable CVs').click()
    expect(page.locator('[data-history-item]:visible')).to_have_count(2)
    expect(page.locator('#history-filter-count')).to_have_text('Showing 2 of 4 entries')
    assert page.locator('a[href="/workspace/download/newer/pdf"]').count() == 1
    assert page.locator('a[href="/workspace/download/no-files/pdf"]').count() == 0


def test_filters_combine_and_reset(history_page):
    page = history_page
    page.get_by_label('Batch', exact=True).select_option('a' * 32)
    page.get_by_label('Application recommendation').select_option('APPLY')
    page.get_by_label('Company', exact=True).fill('alp')
    expect(page.locator('[data-history-item]:visible')).to_have_count(1)
    page.get_by_label('Role', exact=True).fill('missing')
    expect(page.locator('#history-filter-empty')).to_be_visible()
    page.get_by_role('button', name='Clear filters').click()
    expect(page.locator('[data-history-item]:visible')).to_have_count(4)
    expect(page.get_by_label('Sort by')).to_have_value('date_desc')


def test_local_time_range_and_invalid_range(history_page):
    page = history_page
    # Warsaw is UTC+1 in November: 13:00 local is exactly 12:00 UTC.
    page.get_by_label('From date and time').fill('2026-11-06T13:00')
    page.get_by_label('Until date and time').fill('2026-11-06T13:00')
    expect(page.locator('[data-history-item]:visible')).to_have_count(1)
    assert page.locator('[data-history-item]:visible').get_attribute('data-company') == 'alpha'
    page.get_by_label('Until date and time').fill('2026-11-06T12:00')
    expect(page.locator('#history-filter-error')).to_be_visible()
    expect(page.locator('[data-history-item]:visible')).to_have_count(0)


def test_sort_names_both_directions_and_unknown_times_last(history_page):
    page = history_page
    page.get_by_label('Sort by').select_option('company_desc')
    assert page.locator('[data-entry-type="generated"]').first.get_attribute('data-company') == 'zulu'
    page.get_by_label('Sort by').select_option('name_asc')
    assert page.locator('[data-entry-type="generated"]').first.get_attribute('data-company') == 'alpha'
    page.get_by_label('Sort by').select_option('date_asc')
    assert page.locator('[data-entry-type="generated"]').last.get_attribute('data-company') == 'missing'


def test_keyboard_and_filter_panel_fit_mobile(history_page):
    page = history_page
    page.get_by_role('button', name='Show downloadable CVs').focus()
    page.keyboard.press('Enter')
    expect(page.locator('[data-history-item]:visible')).to_have_count(2)
    assert page.locator('.history-filters').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1')
