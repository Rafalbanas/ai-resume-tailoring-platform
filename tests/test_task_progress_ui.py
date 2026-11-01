"""Task polling and URL bootstrap must work without any inline script permission."""
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright

from app.services.ui_language import ui_text


@pytest.mark.parametrize('root', ['', '/workspace'])
@pytest.mark.parametrize('status', ['completed', 'failed'])
def test_task_polls_under_strict_csp_and_handles_result(root, status):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    env.filters['ui_text'] = ui_text
    hostile_model = '\"><script>window.injected=true</script>'
    task = SimpleNamespace(task_id='a' * 32, kind='tailor', status='queued', stage='Waiting',
        created_at='2026-10-17T10:00:00Z', started_at=None, execution_duration_seconds=None,
        payload={'job': {}}, error='', token_usage={'calls': 1, 'completed_calls': 0, 'model': hostile_model})
    html = env.get_template('task_progress.html').render(task=task, app_root_path=root,
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), asset_version='test', csrf_token='synthetic')
    assert '<script nonce=' not in html
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors, polls = [], []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            path = route.request.url.split('fixture.test', 1)[1].split('?')[0]
            if path.endswith('/static/app.js') or path.endswith('/static/task_progress.js'):
                route.fulfill(body=Path('static', path.rsplit('/', 1)[1]).read_text(), content_type='application/javascript')
            elif path == root + '/tasks/' + task.task_id:
                polls.append(path)
                route.fulfill(json={'status': status, 'stage': 'Finished', 'execution_duration_seconds': 2,
                    'error': 'Synthetic processing failure', 'result': {'redirect_url': '/analysis/synthetic'}})
            elif path == root + '/progress':
                route.fulfill(body=html, content_type='text/html', headers={
                    'Content-Security-Policy': "default-src 'self'; script-src 'self'; connect-src 'self'"})
            else:
                route.fulfill(body='')
        page.route('**/*', serve)
        page.goto('http://fixture.test' + root + '/progress')
        assert page.evaluate('typeof window.cvAppUrl') == 'function'
        assert page.evaluate('window.injected') is None
        expect(page.locator('#token-detail')).to_contain_text(hostile_model)
        if status == 'completed':
            page.wait_for_url('**' + root + '/analysis/synthetic')
        else:
            expect(page.locator('#error-message')).to_have_text('Synthetic processing failure', timeout=5000)
            expect(page.locator('#error-container')).to_be_visible()
        assert len(polls) == 1
        assert not errors
        browser.close()


@pytest.mark.parametrize('root', ['', '/workspace'])
def test_queue_panel_keeps_tasks_visible_when_paused_and_escapes_labels(root):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    hostile = '<img src=x onerror=alert(1)>'
    task = {'task_id': 'b' * 32, 'company': hostile, 'role': 'Engineer', 'stage': 'Waiting', 'model': None}
    html = env.get_template('queue_panel.html').render(
        queue_activity={'paused': True, 'running_tasks': [task], 'queued_tasks': [task]},
        app_root_path=root, csrf_token='synthetic')
    assert 'Queue paused' in html
    assert 'Processing now' in html and 'Waiting' in html
    assert '<img' not in html and '&lt;img' in html
    assert f'action="{root}/queue/resume"' in html
    assert f'action="{root}/queue/tasks/{task["task_id"]}/reject"' in html
    assert html.count('Reject waiting task') == 1


@pytest.mark.parametrize('root', ['', '/workspace'])
def test_task_activity_updates_safely_and_running_timer_uses_start_time(root):
    from datetime import datetime, timedelta, timezone
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    env.filters['ui_text'] = ui_text
    now = datetime.now(timezone.utc)
    task = SimpleNamespace(task_id='a' * 32, kind='tailor', status='queued', stage='Waiting',
        created_at=(now - timedelta(hours=1)).isoformat(), started_at=None, execution_duration_seconds=None,
        payload={'job': {}}, error='', token_usage={})
    html = env.get_template('task_progress.html').render(task=task, app_root_path=root,
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), asset_version='test', csrf_token='synthetic')
    hostile = '<script>window.injected=true</script>'
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            path = route.request.url.split('fixture.test', 1)[1].split('?')[0]
            if path.endswith(('/static/app.js', '/static/task_progress.js')):
                route.fulfill(body=Path('static', path.rsplit('/', 1)[1]).read_text(), content_type='application/javascript')
            elif path == root + '/tasks/' + task.task_id:
                route.fulfill(json={'status': 'running', 'started_at': (now - timedelta(seconds=4)).isoformat(), 'stage': 'Analyzing',
                    'activity': {'queue_position': None, 'running_tasks': [{'task_id': 'b' * 32, 'company': hostile, 'role': 'Engineer', 'stage': 'Analyzing'}]}})
            elif path == root + '/progress':
                route.fulfill(body=html, content_type='text/html')
            else:
                route.fulfill(body='')

        page.route('**/*', serve)
        page.goto('http://fixture.test' + root + '/progress')
        expect(page.locator('#running-tasks-list')).to_contain_text(hostile, timeout=5000)
        expect(page.locator('#running-tasks-list a')).to_have_attribute('href', root + '/tasks/' + 'b' * 32 + '/view')
        expect(page.locator('#task-timer')).to_have_text(re.compile(r'Elapsed: \d+s'))
        assert page.evaluate('window.injected') is None
        assert not errors
        browser.close()
