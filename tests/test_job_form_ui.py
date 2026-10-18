"""Browser regressions for failed/uncertain job submissions; never call live AI."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright


@pytest.fixture
def job_page():
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    html = env.get_template('index.html').render(
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), asset_version='test',
        csrf_token='synthetic', fallback_enabled=True, ollama_model='synthetic', gemini_model='synthetic')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            if route.request.url.split('?')[0].endswith('/static/app.js'):
                route.fulfill(body=Path('static/app.js').read_text(), content_type='application/javascript')
            elif route.request.url == 'http://fixture.test/':
                route.fulfill(body=html, content_type='text/html', headers={
                    'Content-Security-Policy': "default-src 'self'; script-src 'self'; connect-src 'self'"})
            else:
                route.fulfill(body='')
        page.route('**/*', serve)
        page.goto('http://fixture.test/')
        page.locator('#company').fill('Synthetic')
        page.locator('#role').fill('Support Engineer')
        page.locator('#job-description').fill('Support verified Python automation and Linux workflows.')
        yield page, errors
        browser.close()


@pytest.mark.parametrize('failure', ['validation', 'server', 'unauthenticated', 'csrf', 'limited', 'network', 'timeout'])
def test_failed_submission_recovers_without_reposting_or_losing_text(job_page, failure):
    page, errors = job_page
    calls = []
    def respond(route):
        calls.append(route.request.post_data)
        if failure == 'network':
            route.abort('failed')
        elif failure == 'timeout':
            # Hold the response until AbortController cancels the request.
            pass
        else:
            route.fulfill(status={'validation': 422, 'unauthenticated': 401, 'csrf': 403, 'limited': 429}.get(failure, 503),
                          content_type='text/html', body='<h1>Request rejected</h1>')
    page.route('**/analyze', respond)
    if failure == 'timeout':
        page.evaluate('''() => {
            const original = window.setTimeout;
            window.setTimeout = (fn, delay, ...args) => original(fn, delay === 20000 ? 30 : delay, ...args);
        }''')
    page.locator('#submit').click()
    expect(page.locator('#submit')).to_be_enabled(timeout=3000)
    expect(page.locator('#fetch-status')).to_have_class('fetch-status error')
    assert len(calls) == 1
    assert not errors
    assert page.locator('#job-description').input_value() == 'Support verified Python automation and Linux workflows.'
    assert page.url == 'http://fixture.test/'


def test_successful_submission_navigates_to_task(job_page):
    page, errors = job_page
    page.route('**/analyze', lambda route: route.fulfill(status=202, json={
        'task_id': 'synthetic', 'view_url': '/tasks/synthetic/view'}))
    page.locator('#submit').click()
    page.wait_for_url('**/tasks/synthetic/view')
    assert not errors


@pytest.mark.parametrize('action,path,deadline', [
    ('fetch-job', '/api/extract-job-url', 60000),
    ('clean-job-text', '/api/clean-job-text', 15000),
])
def test_offer_request_timeout_releases_controls_and_keeps_text(job_page, action, path, deadline):
    page, errors = job_page
    page.locator('#job-url').fill('https://example.com/job')
    page.route('**' + path, lambda route: None)
    page.evaluate('''(deadline) => {
        const original = window.setTimeout;
        window.setTimeout = (fn, delay, ...args) => original(fn, delay === deadline ? 30 : delay, ...args);
    }''', deadline)
    page.locator('#' + action).click()
    expect(page.locator('#fetch-status')).to_have_class('fetch-status error')
    expect(page.locator('#fetch-job')).to_be_enabled()
    expect(page.locator('#clean-job-text')).to_be_enabled()
    assert page.locator('#job-description').input_value() == 'Support verified Python automation and Linux workflows.'
    assert not errors


def test_pending_submission_ignores_repeated_submit_events(job_page):
    page, errors = job_page
    calls = []
    def pending(route):
        calls.append(route.request.post_data)
    page.route('**/analyze', pending)
    page.locator('#submit').click()
    page.locator('#job-form').evaluate("form => form.requestSubmit()")
    page.wait_for_timeout(100)
    assert len(calls) == 1
    assert page.locator('#submit').is_disabled()
    assert not errors


@pytest.mark.parametrize('reason,message', [
    ('blocked', 'HTTP 403/429'),
    ('timeout', 'timed out'),
    ('description_unavailable', 'page was downloaded'),
])
def test_offer_failure_explains_reason_and_keeps_entered_text(job_page, reason, message):
    page, errors = job_page
    page.locator('#job-url').fill('https://pracuj.pl/praca/example,oferta,123')
    page.route('**/api/extract-job-url', lambda route: route.fulfill(json={
        'extraction_method': 'manual_required', 'job_description': '', 'failure_reason': reason,
    }))
    page.locator('#fetch-job').click()
    expect(page.locator('#fetch-status')).to_contain_text(message)
    expect(page.locator('#fetch-job')).to_be_enabled()
    assert page.locator('#job-description').input_value() == 'Support verified Python automation and Linux workflows.'
    assert not errors
