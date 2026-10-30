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
