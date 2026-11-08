"""Synthetic browser regression under strict script CSP and reverse-proxy roots."""
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import Environment, FileSystemLoader, select_autoescape
from playwright.sync_api import expect, sync_playwright

from app.services.ui_language import ui_text


@pytest.mark.parametrize('root', ['', '/workspace'])
def test_cancel_confirmation_waiting_state_and_terminal_results(root, tmp_path):
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    env.filters['ui_text'] = ui_text
    task = SimpleNamespace(task_id='a' * 32, kind='batch', status='running', stage='Analyzing synthetic offer',
        created_at='2026-10-17T10:00:00Z', started_at='2026-10-17T10:00:01Z', execution_duration_seconds=None,
        payload={'job': {}}, result={'items': [{'draft_id': 'd' * 32, 'status': 'draft_ready'}]},
        cancellation_requested=False, error='', token_usage={})
    deploy = {'in_progress': True, 'phase': 'waiting_for_tasks', 'drain_seconds_remaining': 80}
    posts, polls, errors, views = [], [], [], []

    def html():
        return env.get_template('task_progress.html').render(task=task, app_root_path=root,
            request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), asset_version='test',
            csrf_token='synthetic', deployment_status=deploy)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1280, 'height': 1000})
        page.on('pageerror', lambda error: errors.append(str(error)))

        def serve(route):
            path = route.request.url.split('fixture.test', 1)[1].split('?')[0]
            if '/static/' in path:
                asset = Path('static') / path.split('/static/', 1)[1]
                kind = 'application/javascript' if asset.suffix == '.js' else 'text/css'
                route.fulfill(body=asset.read_bytes() if asset.is_file() else b'', content_type=kind)
            elif path == root + f'/queue/tasks/{task.task_id}/cancel-batch':
                posts.append(route.request.post_data)
                task.cancellation_requested = True
                views.append(task.status)
                # Render the post-submit page directly: endpoint/303 is covered
                # by integration tests; intercepted redirect chains bypass routes.
                route.fulfill(body=html(), content_type='text/html')
            elif path == root + '/tasks/' + task.task_id:
                polls.append(path)
                route.fulfill(json={'status': task.status, 'cancellation_requested': task.cancellation_requested,
                                    'deployment': deploy, 'stage': task.stage})
            elif path == root + '/progress':
                views.append(task.status)
                route.fulfill(body=html(), content_type='text/html', headers={
                    'Content-Security-Policy': "default-src 'self'; script-src 'self'; connect-src 'self'; style-src 'self' 'unsafe-inline'"})
            else:
                route.fulfill(body='')

        page.route('**/*', serve)
        page.goto('http://fixture.test' + root + '/progress')
        button = page.get_by_role('button', name='Cancel remaining offers')
        expect(button).to_be_visible()
        expect(page.locator('#deployment-notice')).to_be_visible()
        expect(page.locator('#deployment-detail')).to_contain_text('not an estimate')
        page.evaluate("document.documentElement.style.zoom = '2'")
        button.focus()
        expect(button).to_be_focused()
        assert button.evaluate("el => { const s = getComputedStyle(el); return s.outlineStyle !== 'none' && s.outlineWidth !== '0px'; }")
        button.scroll_into_view_if_needed()
        bounds = button.bounding_box()
        assert bounds['x'] >= 0 and bounds['x'] + bounds['width'] <= 1280
        page.screenshot(path=str(tmp_path / 'synthetic-batch-cancel-zoom.png'))

        def dismiss(dialog):
            assert 'saved analyses and CVs are kept' in dialog.message
            dialog.dismiss()

        page.once('dialog', dismiss)
        button.press('Enter')
        assert not posts
        expect(button).to_be_visible()
        page.once('dialog', lambda dialog: dialog.accept())
        button.press('Enter')
        expect(page.locator('#batch-cancel-requested')).to_be_visible()
        expect(page.locator('#cancel-batch-form')).to_be_hidden()
        assert posts == ['csrf_token=synthetic']
        # Continue polling at the normal GET status page (the real form uses 303).
        page.goto('http://fixture.test' + root + '/progress')
        expect(page.locator('#batch-cancel-requested')).to_be_visible()
        task.status = 'cancelled'
        expect(page.locator('#batch-cancelled-results')).to_be_visible(timeout=7000)
        expect(page.locator('#task-status-text')).to_contain_text('Cancelled')
        expect(page.locator('#batch-cancelled-results a').first).to_have_attribute(
            'href', root + '/analysis/' + 'd' * 32)
        expect(page.locator('#batch-cancellation-controls')).to_be_hidden()
        assert views == ['running', 'running', 'running', 'cancelled']  # Exactly one terminal reload.
        assert len(posts) == 1 and polls
        terminal_polls = len(polls)
        page.clock.install()
        page.clock.fast_forward(5000)
        assert len(polls) == terminal_polls and len(posts) == 1
        assert not errors
        browser.close()
