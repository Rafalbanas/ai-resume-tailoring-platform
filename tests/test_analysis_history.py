"""Started jobs remain recoverable without generating a CV or calling an API."""
import json
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from fastapi.testclient import TestClient

from app.main import app
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.storage import Storage
from app.services.task_manager import TaskKind, TaskManager, TaskStatus


def job():
    return JobRequest(company='Synthetic Netige', role='IT Specialist',
                      job_url='https://jobs.example.test/it-specialist?ref=history',
                      job_description='Requirements\nExperience in IT support and Windows troubleshooting.')


def draft(storage, resume_payload):
    source = job()
    response = WorkflowResponse(
        analysis=JobAnalysis(company=source.company, role=source.role, strong_matches=[], partial_matches=[],
                             missing_requirements=[], recommendation='REVIEW', match_level='LOW'),
        resume=TailoredResume.model_validate(resume_payload), truth_warnings=[],
    )
    return storage.save_draft(source, response), response


def test_started_job_is_on_disk_with_url_before_worker_runs(tmp_path):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    reloaded = TaskManager(tmp_path).get_task(task.task_id)
    assert reloaded.payload['job']['job_url'] == str(job().job_url)
    rows = Storage(tmp_path).analysis_history()
    assert len(rows) == 1 and rows[0]['status'] == 'queued'
    assert rows[0]['job_url'] == str(job().job_url)
    assert rows[0]['edit_url'] == f'/?from_task={task.task_id}'


@pytest.mark.parametrize('status', [TaskStatus.RUNNING, TaskStatus.FAILED])
def test_running_and_failed_jobs_stay_in_history(tmp_path, status):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    task.status = status
    manager._save_task(task)
    row = Storage(tmp_path).analysis_history()[0]
    assert row['status'] == status.value and row['job_url'] == str(job().job_url)


@pytest.mark.asyncio
async def test_restart_keeps_interrupted_job_and_link(tmp_path):
    manager = TaskManager(tmp_path)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    task.status = TaskStatus.RUNNING
    manager._save_task(task)
    assert await TaskManager(tmp_path).recover_on_startup() == 1
    row = Storage(tmp_path).analysis_history()[0]
    assert row['interrupted'] and row['status'] == 'failed'
    assert row['job_url'] == str(job().job_url)


def test_report_without_export_and_legacy_orphan_draft_are_visible(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    draft_id, _ = draft(storage, resume_payload)
    path = storage.drafts_dir / f'{draft_id}.json'
    payload = json.loads(path.read_text())
    payload.pop('created_at')  # Previous versions did not store timestamps.
    path.write_text(json.dumps(payload))
    before = path.read_bytes()
    rows = storage.analysis_history()
    assert len(rows) == 1 and rows[0]['status'] == 'report_ready'
    assert rows[0]['view_url'] == f'/analysis/{draft_id}'
    assert rows[0]['edit_url'] == f'/?from_draft={draft_id}'
    assert path.read_bytes() == before


def test_completed_task_draft_and_generated_cv_are_not_duplicated(tmp_path, resume_payload):
    storage, manager = Storage(tmp_path), TaskManager(tmp_path)
    draft_id, response = draft(storage, resume_payload)
    task = manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    task.status = TaskStatus.COMPLETED
    task.result = {'draft_id': draft_id}
    manager._save_task(task)
    assert len(storage.analysis_history()) == 1
    assert storage.analysis_history()[0]['status'] == 'report_ready'
    slug, _ = storage.save_application(job(), response.analysis, response.resume, [], draft_id=draft_id)
    assert storage.analysis_history() == []
    assert len(storage.history()) == 1
    storage.delete_application(slug)
    assert storage.analysis_history() == []


def test_malformed_records_do_not_hide_valid_history(tmp_path):
    storage = Storage(tmp_path)
    manager = TaskManager(tmp_path)
    manager.create_task(TaskKind.TAILOR, {'job': job().model_dump(mode='json')}, 'synthetic')
    (manager.tasks_dir / ('a' * 32 + '.json')).write_text('{broken')
    (storage.drafts_dir / ('b' * 32 + '.json')).write_text('{}')
    bad = manager.create_task(TaskKind.COMPARE, {'job': job().model_dump(mode='json')}, 'comparison')
    assert len(storage.analysis_history()) == 1
    assert bad.task_id not in str(storage.analysis_history())


def login(client):
    client.get('/login')
    result = client.post('/login', data={'username': 'audit-tests', 'password': 'isolated-test-password',
                                       'csrf_token': client.cookies.get('csrf_token')})
    assert result.status_code == 200


def test_history_and_return_to_form_preserve_link_without_provider_calls(monkeypatch, resume_payload):
    with TestClient(app) as client:
        login(client)
        app.state.task_manager.stop_worker()
        calls = []
        async def forbidden(*args, **kwargs):
            calls.append(True)
            pytest.fail('Reading history must not start an analysis')
        monkeypatch.setattr(app.state.provider, 'tailor', forbidden)
        result = client.post('/analyze', data={**job().model_dump(mode='json'),
                             'csrf_token': client.cookies.get('csrf_token')}, headers={'Accept': 'application/json'})
        assert result.status_code == 202
        task_id = result.json()['task_id']
        page = client.get('/history')
        assert page.status_code == 200 and 'Queued' in page.text
        soup = BeautifulSoup(page.text, 'html.parser')
        assert soup.select_one('a.source-link')['href'] == str(job().job_url)
        assert soup.select_one(f'a[href="/?from_task={task_id}"]')
        restored = BeautifulSoup(client.get(f'/?from_task={task_id}').text, 'html.parser')
        assert restored.select_one('#job-url')['value'] == str(job().job_url)
        assert job().job_description in restored.select_one('textarea[name="job_description"]').text
        draft_id, _ = draft(app.state.storage, resume_payload)
        restored = BeautifulSoup(client.get(f'/?from_draft={draft_id}').text, 'html.parser')
        assert restored.select_one('#job-url')['value'] == str(job().job_url)
        assert not calls
        assert client.get('/?from_draft=../../escape').status_code == 404


@pytest.mark.asyncio
async def test_history_requires_authentication(monkeypatch):
    from fastapi import HTTPException

    from app.routes import web
    def unauthorized(_):
        raise HTTPException(401)
    monkeypatch.setattr(web, 'guard', unauthorized)
    with pytest.raises(HTTPException) as error:
        await web.history(SimpleNamespace())
    assert error.value.status_code == 401


def test_history_links_respect_root_path_and_escape_text(tmp_path):
    from pathlib import Path

    from jinja2 import Environment, FileSystemLoader, select_autoescape

    manager = TaskManager(tmp_path)
    source = job().model_copy(update={'company': '<script>bad()</script>'})
    task = manager.create_task(TaskKind.TAILOR, {'job': source.model_dump(mode='json')}, 'synthetic')
    template = Environment(loader=FileSystemLoader(Path('templates')), autoescape=select_autoescape(['html'])).get_template('history.html')
    page = template.render(rows=[], analyses=Storage(tmp_path).analysis_history(), app_root_path='/workspace',
                           request=SimpleNamespace(state=SimpleNamespace(authenticated=False)))
    assert '<script>bad()</script>' not in page
    assert f'href="/workspace/?from_task={task.task_id}"' in page
    assert f'href="/workspace/tasks/{task.task_id}/view"' in page
    assert 'Clear generated CVs' in page
