import json
import shutil

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse
from app.services.storage import Storage
from app.services.task_manager import TaskManager
from tests.test_offer_deadline_integration import seed
from tests.test_queue_controls import login
from tests.test_shared_login import runtimes, sign_in
from tests.test_shared_login import shared_app as _shared_app

shared_app = _shared_app


@pytest.mark.parametrize('kind', ['draft', 'application'])
@pytest.mark.parametrize('salary', ['10 000–15 000 PLN netto / mies. B2B',
                                   '10 000 PLN brutto / mies. UoP\n15 000 PLN netto + VAT / mies. B2B'])
def test_salary_edit_clear_and_artifacts_unchanged(tmp_path, resume_payload, kind, salary):
    storage = Storage(tmp_path)
    draft, slug, folder = seed(storage, resume_payload)
    original = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    draft_path = storage.drafts_dir / f'{draft}.json'
    original[draft_path] = draft_path.read_bytes()
    identifier = draft if kind == 'draft' else slug
    storage.update_offer_salary(kind, identifier, salary)
    job = storage.load_draft(draft)[0] if kind == 'draft' else storage.load_application(slug)[0]
    assert job.salary_range == salary
    if kind == 'application':
        assert storage.history()[0]['salary_range'] == job.salary_range
    else:
        shutil.rmtree(folder)
        assert storage.analysis_history()[0]['salary_range'] == job.salary_range
        original = {draft_path: original[draft_path]}
    storage.update_offer_salary(kind, identifier, '')
    job = storage.load_draft(draft)[0] if kind == 'draft' else storage.load_application(slug)[0]
    assert job.salary_range == ''
    assert all(p.read_bytes() == content for p, content in original.items())
    assert not list(tmp_path.rglob('*.tmp'))


def test_salary_legacy_recovery_and_explicit_clear():
    data = dict(company='Synthetic', role='Support', job_description='Support Python and Linux. Salary: 100–150 PLN/h')
    assert '100–150 PLN' in JobRequest(**data).salary_range
    assert JobRequest(**data, salary_range='').salary_range == ''


def test_salary_route_and_form(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app, root_path='/tailor') as client:
        path = '/offers/draft/' + 'a' * 32 + '/salary'
        assert client.post(path, data={'csrf_token': 'bad'}).status_code == 401
        login(client)
        draft, slug, folder = seed(app.state.storage, resume_payload)
        path = f'/offers/application/{slug}/salary'
        assert client.post(path, data={'csrf_token': 'bad'}).status_code == 403
        data = {'csrf_token': client.cookies.get('csrf_token'), 'salary_range': '100–150 PLN/h B2B'}
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == '/tailor/history'
        assert '100–150 PLN/h B2B' in client.get('/history').text
        assert '>100–150 PLN/h B2B</textarea>' in client.get('/?from_cv=' + slug).text
        data['salary_range'] = '<script>alert(1)</script>'
        assert client.post(path, data=data, follow_redirects=False).status_code == 303
        assert '&lt;script&gt;alert(1)&lt;/script&gt;' in client.get('/history').text
        data['salary_range'] = 'x' * 501
        assert client.post(path, data=data).status_code == 422
        data['salary_range'] = '200 PLN/h'
        assert client.post('/offers/draft/' + 'b' * 32 + '/salary', data=data).status_code == 404
        monkeypatch.setattr(app.state.settings, 'demo_mode', True)
        assert client.post(path, data=data).status_code == 403


@pytest.mark.parametrize('salary', ['Salary: 100–150 PLN/h',
                                   '100–150 PLN/h B2B\n10 000–14 000 PLN brutto UoP'])
def test_salary_submit_and_clean_paste(monkeypatch, salary):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        data = {'csrf_token': client.cookies.get('csrf_token'), 'company': 'Synthetic', 'role': 'Support',
                'job_description': 'Support Python and Linux workflows.\n' + salary, 'llm_provider': 'mock'}
        result = client.post('/analyze', data=data, headers={'Accept': 'application/json'})
        assert result.status_code == 202
        task = app.state.task_manager.get_task(result.json()['task_id'])
        assert '100–150 PLN' in task.payload['job']['salary_range']
        if '\n' in salary:
            assert task.payload['job']['salary_range'] == salary
        assert '100–150 PLN' in client.get('/?from_task=' + task.task_id).text
        response = client.post('/api/clean-job-text', json={'text': data['job_description']},
                               headers={'X-CSRF-Token': client.cookies.get('csrf_token')})
        assert response.status_code == 200
        assert '100–150 PLN' in response.json()['salary_range']
        if '\n' in salary:
            assert response.json()['salary_range'] == salary
        data['salary_range'] = '200 PLN/h'
        other = client.post('/analyze', data=data, headers={'Accept': 'application/json'})
        assert other.json()['task_id'] != task.task_id


def test_salary_account_isolation_and_delete(tmp_path, resume_payload):
    owner, other = Storage(tmp_path / 'owner'), Storage(tmp_path / 'other')
    draft, slug, _ = seed(owner, resume_payload)
    with pytest.raises(FileNotFoundError):
        other.update_offer_salary('application', slug, '200 PLN/h')
    owner.update_offer_salary('draft', draft, '200 PLN/h')
    owner.update_offer_salary('application', slug, '300 PLN/h')
    duplicate = owner.duplicate_application(slug)
    assert owner.load_application(duplicate)[0].salary_range == '300 PLN/h'
    owner.delete_application(slug)
    assert not (owner.drafts_dir / f'{draft}.salary.json').exists()
    assert owner.load_application(duplicate)[0].salary_range == '300 PLN/h'


def test_legacy_saved_offer_visible_in_history(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    _, _, folder = seed(storage, resume_payload)
    path = folder / 'job.json'
    data = json.loads(path.read_text())
    data.pop('salary_range', None)
    data['job_description'] += '\nSalary: 100–150 PLN/h'
    path.write_text(json.dumps(data))
    assert '100–150 PLN' in storage.history()[0]['salary_range']


def test_custom_offer_salary_rejected_and_hidden(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        draft, _, folder = seed(app.state.storage, resume_payload)
        job, response = app.state.storage.load_draft(draft)
        job = JobRequest(company='Custom CV', role='Support', workflow='custom',
                         custom_instructions='Keep verified support facts.')
        custom = app.state.storage.save_draft(job, WorkflowResponse.model_validate(response.model_dump()))
        shutil.rmtree(folder)
        (app.state.storage.drafts_dir / f'{draft}.json').unlink()
        assert 'Salary range / Widełki' not in client.get('/history').text
        result = client.post(f'/offers/draft/{custom}/salary', data={
            'csrf_token': client.cookies.get('csrf_token'), 'salary_range': '100 PLN/h'})
        assert result.status_code == 422


def test_salary_http_account_isolation(shared_app, monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(shared_app) as client:
        owner, demo = runtimes(shared_app)
        draft, slug, _ = seed(owner.state.storage, resume_payload)
        assert sign_in(client, 'demo').status_code == 303
        monkeypatch.setattr(demo.state.settings, 'demo_mode', False)
        for kind, identifier in [('draft', draft), ('application', slug)]:
            response = client.post(f'/offers/{kind}/{identifier}/salary?account=owner',
                data={'csrf_token': client.cookies.get('csrf_token'), 'salary_range': '100 PLN/h'},
                headers={'X-Account': 'owner'}, follow_redirects=False)
            assert response.status_code == 404
        assert owner.state.storage.load_draft(draft)[0].salary_range == ''


def test_salary_disk_quota_blocks_write(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        draft, _, _ = seed(app.state.storage, resume_payload)
        def over_quota():
            raise HTTPException(507, 'Synthetic quota reached')
        monkeypatch.setattr(app.state.resource_budget, 'check_disk', over_quota)
        response = client.post(f'/offers/draft/{draft}/salary', data={
            'csrf_token': client.cookies.get('csrf_token'), 'salary_range': '100 PLN/h'})
        assert response.status_code == 507
        assert app.state.storage.load_draft(draft)[0].salary_range == ''
