from playwright.sync_api import expect

from tests.test_job_form_ui import job_page as job_page


def test_custom_mode_reuses_prompt_and_does_not_require_job_fields(job_page):
    page, errors = job_page
    page.locator('#cv-workflow').select_option('custom')
    expect(page.locator('#job-identity-fields')).to_be_hidden()
    expect(page.locator('#job-url-field')).to_be_hidden()
    expect(page.locator('#clean-job-text')).to_be_hidden()
    expect(page.locator('#prompt-label')).to_have_text('What would you like to change?')
    expect(page.locator('#submit-label')).to_have_text('Generate CV')
    page.locator('#company').evaluate("node => node.value = ''")
    page.locator('#role').evaluate("node => node.value = ''")
    page.locator('#job-description').fill('Emphasize verified SQL and troubleshooting.')
    calls = []
    def respond(route):
        calls.append(route.request.post_data)
        route.fulfill(status=202, json={'task_id': 'custom', 'view_url': '/tasks/custom/view'})
    page.route('**/analyze', respond)
    page.locator('#submit').click()
    page.wait_for_url('**/tasks/custom/view')
    assert len(calls) == 1 and 'Emphasize verified SQL' in calls[0]
    assert not errors


def test_ai_editor_focused_layout_saved_template_and_mobile_preview(tmp_path):
    from pathlib import Path
    from types import SimpleNamespace

    from jinja2 import Environment, FileSystemLoader, select_autoescape
    from playwright.sync_api import sync_playwright

    from app.services.cv_editor import CVEditorStore, split_sections
    from app.services.text_cv_export import export_to_pdf

    store = CVEditorStore(tmp_path)
    text = Path('tests/fixtures/modern_sidebar.txt').read_text()
    identifier = store.create('Synthetic CV', text, template_name='modern_sidebar')
    doc = store.load(identifier)
    env = Environment(loader=FileSystemLoader('templates'), autoescape=select_autoescape(['html']))
    html = env.get_template('custom_cv_editor.html').render(
        request=SimpleNamespace(state=SimpleNamespace(authenticated=False)), asset_version='test',
        csrf_token='synthetic', document=doc, sections=split_sections(text), changes=[])
    pdf = export_to_pdf(text, 'modern_sidebar')
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        page = browser.new_page(viewport={'width': 1440, 'height': 1100})
        errors = []
        page.on('pageerror', lambda error: errors.append(str(error)))
        def serve(route):
            path = route.request.url.split('?')[0]
            if path.endswith('/static/app.css'):
                route.fulfill(body=Path('static/app.css').read_text(), content_type='text/css')
            elif path.endswith('/static/app.js'):
                route.fulfill(body=Path('static/app.js').read_text(), content_type='application/javascript')
            elif path.endswith('/preview'):
                route.fulfill(body=pdf, content_type='application/pdf')
            else:
                route.fulfill(body=html, content_type='text/html')
        page.route('**/*', serve)
        page.goto(f'http://fixture.test/custom-cvs/{identifier}')
        expect(page.get_by_label('What would you like to change?')).to_be_visible()
        expect(page.locator('[name="template_name"]')).to_have_value('modern_sidebar')
        expect(page.locator('.cv-text-editor')).to_be_hidden()
        expect(page.locator('.cv-pdf-preview')).to_have_attribute('src', f'/custom-cvs/{identifier}/preview#view=FitH')
        assert '?template=' not in page.get_by_role('link', name='Download PDF').get_attribute('href')
        controls = page.locator('.custom-editor-controls').bounding_box()
        preview = page.locator('.custom-editor-preview').bounding_box()
        assert controls['x'] + controls['width'] <= preview['x']
        page.screenshot(path=str(tmp_path / 'editor-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        expect(page.get_by_role('button', name='Propose changes')).to_be_visible()
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.locator('#cv-manual summary').click()
        expect(page.locator('.cv-text-editor')).to_be_visible()
        assert page.locator('.cv-text-editor').input_value() == text
        page.screenshot(path=str(tmp_path / 'editor-mobile.png'), full_page=True)
        assert not errors
        browser.close()


def test_mode_switch_preserves_prompt_and_paste_import_is_separate(job_page):
    page, errors = job_page
    original = page.locator('#job-description').input_value()
    page.locator('#cv-workflow').select_option('custom')
    page.locator('#custom-source').select_option('paste')
    expect(page.locator('#pasted-cv-field')).to_be_visible()
    expect(page.locator('#prompt-field')).to_be_hidden()
    page.locator('#pasted-cv').fill('Ada Example\nExperience\nExample Ltd | 2022–Present')
    calls = []
    def imported(route):
        calls.append(route.request.post_data)
        route.fulfill(status=202, json={'view_url': '/custom-cvs/0123456789abcdef0123456789abcdef'})
    page.route('**/custom-cvs/import', imported)
    page.locator('#submit').click()
    page.wait_for_url('**/custom-cvs/0123456789abcdef0123456789abcdef')
    assert len(calls) == 1 and 'Ada Example' in calls[0]
    assert original in calls[0]  # retained as draft input, not used to modify the imported source
    assert not errors


def test_custom_validation_keeps_instruction_text(job_page):
    page, errors = job_page
    page.locator('#cv-workflow').select_option('custom')
    page.locator('#job-description').fill('Tiny')
    page.locator('#submit').click()
    expect(page.locator('#fetch-status')).to_contain_text('at least 10 characters')
    assert page.locator('#job-description').input_value() == 'Tiny'
    page.locator('#cv-workflow').select_option('job')
    expect(page.locator('#job-identity-fields')).to_be_visible()
    expect(page.locator('#submit-label')).to_have_text('Analyze job')
    assert not errors
