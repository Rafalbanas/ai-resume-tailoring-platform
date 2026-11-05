"""Synthetic offer metadata regressions; no provider calls or stored CV rewrites."""
import json
from datetime import date

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.deadline import html_deadline, labelled_deadline
from app.services.job_extractors.jsonld import JsonLdExtractor
from app.services.storage import Storage
from app.services.task_manager import TaskManager
from tests.test_queue_controls import login
from tests.test_shared_login import runtimes, sign_in
from tests.test_shared_login import shared_app as _shared_app

shared_app = _shared_app


def seed(storage, resume_payload):
    job = JobRequest(company='Synthetic', role='Support', job_description='Support Python and Linux workflows.',
                     offer_valid_until='2026-11-30')
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation='APPLY', match_level='HIGH')
    resume = TailoredResume.model_validate(resume_payload)
    response = WorkflowResponse(analysis=analysis, resume=resume, warnings=[])
    draft = storage.save_draft(job, response)
    slug, folder = storage.save_application(job, analysis, resume, [], draft_id=draft)
    for name in ('resume.pdf', 'resume.docx'):
        (folder / name).write_bytes(b'synthetic immutable export')
    return draft, slug, folder


@pytest.mark.parametrize('value', ['2026-02-29', '30.11.2026', '2026-11-30T00:00:00Z', 1796000000, True])
def test_manual_date_is_strict(value):
    with pytest.raises(ValidationError):
        JobRequest(company='Synthetic', role='Support', job_description='Support Python and Linux workflows.', offer_valid_until=value)


@pytest.mark.parametrize('kind', ['draft', 'application'])
def test_sidecars_preserve_every_original_artifact_and_allow_clear(tmp_path, resume_payload, kind):
    storage = Storage(tmp_path)
    draft, slug, folder = seed(storage, resume_payload)
    original = {p: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    draft_path = storage.drafts_dir / f'{draft}.json'
    original[draft_path] = draft_path.read_bytes()
    identifier = draft if kind == 'draft' else slug
    def load():
        return storage.load_draft(draft)[0] if kind == 'draft' else storage.load_application(slug)[0]
    storage.update_offer_deadline(kind, identifier, '2026-12-10')
    assert load().offer_valid_until == date(2026, 12, 10)
    storage.update_offer_deadline(kind, identifier, '')
    assert load().offer_valid_until is None
    assert all(p.read_bytes() == content for p, content in original.items())
    assert not list(tmp_path.rglob('*.tmp'))
    if kind == 'application':
        assert storage.history()[0]['offer_valid_until'] is None


def test_deadline_storage_is_account_local(tmp_path, resume_payload):
    owner, other = Storage(tmp_path / 'owner'), Storage(tmp_path / 'other')
    draft, slug, _ = seed(owner, resume_payload)
    for kind, identifier in [('draft', draft), ('application', slug)]:
        with pytest.raises(FileNotFoundError):
            other.update_offer_deadline(kind, identifier, '2026-12-10')
    assert owner.load_draft(draft)[0].offer_valid_until == date(2026, 11, 30)


def test_duplicate_and_delete_keep_deadline_sidecars_consistent(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    draft, slug, folder = seed(storage, resume_payload)
    storage.update_offer_deadline('draft', draft, '2026-12-10')
    storage.update_offer_deadline('application', slug, '')
    duplicate = storage.duplicate_application(slug)
    assert storage.load_application(duplicate)[0].offer_valid_until is None
    storage.delete_application(slug)
    assert not folder.exists()
    assert not (storage.drafts_dir / f'{draft}.deadline.json').exists()
    assert storage.load_application(duplicate)[0].offer_valid_until is None


def test_draft_history_overlays_date_without_counting_sidecars_as_drafts(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    draft, _, folder = seed(storage, resume_payload)
    # Keep the draft as an unexported report, without deleting it through application cleanup.
    import shutil
    shutil.rmtree(folder)
    storage.update_offer_deadline('draft', draft, '2026-12-10')
    rows = storage.analysis_history()
    assert len(rows) == 1
    assert rows[0]['draft_id'] == draft
    assert rows[0]['offer_valid_until'] == '2026-12-10'


def test_legacy_missing_date_and_explicit_clear(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    draft, slug, folder = seed(storage, resume_payload)
    for path in [folder / 'job.json', folder / 'metadata.json', storage.drafts_dir / f'{draft}.json']:
        data = json.loads(path.read_text())
        (data['job'] if 'job' in data else data).pop('offer_valid_until', None)
        path.write_text(json.dumps(data))
    assert storage.load_application(slug)[0].offer_valid_until is None
    assert storage.load_draft(draft)[0].offer_valid_until is None
    assert storage.history()[0]['offer_valid_until'] is None


def test_custom_draft_does_not_offer_deadline_editing(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        job = JobRequest(company='Custom CV', role='Support', workflow='custom', custom_instructions='Keep verified support facts.')
        analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                               missing_requirements=[], recommendation='APPLY', match_level='HIGH')
        draft = app.state.storage.save_draft(job, WorkflowResponse(analysis=analysis,
                    resume=TailoredResume.model_validate(resume_payload)))
        assert 'Offer valid until' not in client.get('/history').text
        response = client.post(f'/offers/draft/{draft}/deadline', data={
            'csrf_token': client.cookies.get('csrf_token'), 'offer_valid_until': '2026-11-30'})
        assert response.status_code == 422


def test_explicit_dates_only_and_no_related_offer_leak():
    assert labelled_deadline('Published: 2026-11-01\n30 days') is None
    assert labelled_deadline('Offer valid until:\n2026-11-30') == date(2026, 11, 30)
    assert labelled_deadline('Requirements\nSimilar jobs\nOffer valid until: 2026-12-10') is None
    assert labelled_deadline('Offer valid until: 2026-11-30\nApplication deadline: 2026-12-10') is None
    assert html_deadline('<footer>Offer valid until: 2026-11-30</footer>') is None
    assert html_deadline('<main><p>Offer valid until: 2026-11-30</p>'
                         '<aside><p>Offer valid until: 2026-12-10</p></aside></main>') == date(2026, 11, 30)
    assert labelled_deadline('Oferta ważna do: 26.11.2026 (zostały 23 dni)') == date(2026, 11, 26)
    assert labelled_deadline('26 day left (until 01.12.2026)') == date(2026, 12, 1)
    assert labelled_deadline('## **Oferta ważna do:**\n26.11.2026') == date(2026, 11, 26)
    assert labelled_deadline('26 day left') is None
    assert html_deadline('<main><time itemprop="validThrough" datetime="2026-11-30"></time>'
                         '<p>Offer valid until: 2026-12-10</p></main>') is None
    assert html_deadline('<nfj-posting-header><p>Oferta ważna do: 26.11.2026 (zostały 23 dni)</p>'
                         '</nfj-posting-header>') == date(2026, 11, 26)


@pytest.mark.parametrize('jsonld,visible,expected', [
    ('2026-12-01', '01.12.2026', date(2026, 12, 1)),
    ('2026-12-31', '01.12.2026', None),
    (None, '01.12.2026', date(2026, 12, 1)),
])
def test_justjoin_countdown_and_metadata_conflicts(jsonld, visible, expected):
    posting = {'@type': 'JobPosting', 'title': 'Support', 'hiringOrganization': {'name': 'Synthetic'},
               'description': 'Support Python and Linux workflows. ' * 5, 'validThrough': jsonld}
    html = '<h1>Support</h1><script type="application/ld+json">' + json.dumps(posting) + '</script>'
    html += '<div><span role="progressbar"></span><span>26 day left (until ' + visible + ')</span></div>'
    service = JobExtractorService(Settings(_env_file=None))
    candidate, _ = service._extract_html('https://justjoin.it/job-offer/synthetic', html)
    assert candidate.offer_valid_until == expected


def test_duplicate_jsonld_conflict_cannot_be_overwritten_by_html():
    posting = {'@type': 'JobPosting', 'title': 'Support', 'hiringOrganization': {'name': 'Synthetic'},
               'description': 'Support Python and Linux workflows. ' * 5, 'validThrough': '2026-11-30'}
    html = '<script type="application/ld+json">' + json.dumps([posting, {**posting, 'validThrough': '2026-12-10'}]) + '</script>'
    html += '<main><p>Offer valid until: 2026-11-30</p></main>'
    service = JobExtractorService(Settings(_env_file=None))
    candidate, _ = service._extract_html('https://example.com/job', html)
    assert candidate.offer_valid_until is None


def test_deadline_cannot_be_inherited_from_a_different_employer():
    from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate
    class Adapter(BaseExtractor):
        domains = ('example.com',)
        prefer_over_jsonld = True
        def extract(self, html):
            return ExtractionCandidate(company='Actual employer', role='Support', job_description='Verified support work. ' * 6)
    posting = {'@type': 'JobPosting', 'title': 'Support', 'hiringOrganization': {'name': 'Other employer'},
               'description': 'Support Python and Linux workflows. ' * 5, 'validThrough': '2026-11-30'}
    service = JobExtractorService(Settings(_env_file=None))
    service.adapters = (Adapter(),)
    candidate, _ = service._extract_html('https://example.com/job', '<script type="application/ld+json">'
                                         + json.dumps(posting) + '</script>')
    assert candidate.company == 'Actual employer'
    assert candidate.offer_valid_until is None


def test_jsonld_dates_are_posting_scoped_and_conflicts_unknown():
    posting = {'@type': 'JobPosting', 'title': 'Support', 'hiringOrganization': {'name': 'Synthetic'},
               'description': 'Support Python and Linux.', 'validThrough': '2026-11-30T23:59Z'}
    def extract(items):
        return JsonLdExtractor().extract('<script type="application/ld+json">' + json.dumps(items) + '</script>')
    assert extract(posting).offer_valid_until == date(2026, 11, 30)
    assert extract([posting, {**posting, 'validThrough': '2026-12-10'}]).offer_valid_until is None
    assert extract([posting, {**posting, 'title': 'Other'}]).ambiguous
    assert extract({'@type': 'WebPage', 'validThrough': '2026-12-10'}).offer_valid_until is None


def test_deadline_route_auth_csrf_validation_and_history(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        path = '/offers/draft/' + 'a' * 32 + '/deadline'
        assert client.post(path, data={'csrf_token': 'invalid'}).status_code == 401
        login(client)
        draft, slug, _ = seed(app.state.storage, resume_payload)
        path = f'/offers/draft/{draft}/deadline'
        assert client.post(path, data={'csrf_token': 'invalid'}).status_code == 403
        token = client.cookies.get('csrf_token')
        data = {'csrf_token': token, 'offer_valid_until': '2026-02-29'}
        assert client.post(path, data=data).status_code == 422
        data['offer_valid_until'] = '2000-01-01'
        response = client.post(path, data=data, follow_redirects=False)
        assert response.status_code == 303
        assert response.headers['location'] == f'/analysis/{draft}'
        assert app.state.storage.load_draft(draft)[0].offer_valid_until == date(2000, 1, 1)
        response = client.post(f'/offers/application/{slug}/deadline', data=data, follow_redirects=False)
        assert response.status_code == 303
        html = client.get('/history').text
        assert 'Past stated deadline' in html and '2000-01-01' in html
        data['offer_valid_until'] = ''
        assert client.post(f'/offers/application/{slug}/deadline', data=data, follow_redirects=False).status_code == 303
        assert 'Not provided' in client.get('/history').text


def test_clean_paste_api_extracts_explicit_deadline(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        text = 'Synthetic\nSupport Engineer\nRequirements\n' + 'Support Python and Linux workflows. ' * 4
        response = client.post('/api/clean-job-text', json={'text': text + '\nOferta ważna do: 30 listopada 2026'},
                               headers={'X-CSRF-Token': client.cookies.get('csrf_token')})
        assert response.status_code == 200
        assert response.json()['offer_valid_until'] == '2026-11-30'


def test_html_extraction_propagates_date_without_inventing_one():
    service = JobExtractorService(Settings(_env_file=None))
    body = '<main><h1>Support</h1><p>' + 'Support Python and Linux workflows. ' * 8 + '</p>{}</main>'
    candidate, method = service._extract_html('https://example.com/job', body.format('<p>Offer valid until: 2026-11-30</p>'))
    assert service._result(candidate, 'https://example.com/job', method).offer_valid_until == date(2026, 11, 30)
    candidate, _ = service._extract_html('https://example.com/job', body.format('<p>Published: 2026-11-01</p>'))
    assert candidate.offer_valid_until is None


def test_deadline_route_root_path_demo_quota_and_missing(monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app, root_path='/tailor') as client:
        login(client)
        draft, _, _ = seed(app.state.storage, resume_payload)
        path = f'/offers/draft/{draft}/deadline'
        data = {'csrf_token': client.cookies.get('csrf_token'), 'offer_valid_until': '2026-12-10'}
        response = client.post(path, data=data, follow_redirects=False)
        assert response.headers['location'] == f'/tailor/analysis/{draft}'
        restored = client.get('/?from_draft=' + draft).text
        assert 'value="2026-12-10"' in restored
        assert client.post('/offers/draft/' + 'b' * 32 + '/deadline', data=data).status_code == 404
        monkeypatch.setattr(app.state.settings, 'demo_mode', True)
        assert client.post(path, data=data).status_code == 403
        monkeypatch.setattr(app.state.settings, 'demo_mode', False)
        def over_quota():
            raise HTTPException(507, 'Synthetic quota reached')
        monkeypatch.setattr(app.state.resource_budget, 'check_disk', over_quota)
        data['offer_valid_until'] = ''
        assert client.post(path, data=data).status_code == 507
        assert app.state.storage.load_draft(draft)[0].offer_valid_until == date(2026, 12, 10)


def test_initial_form_submits_and_restores_date_without_approving_cv(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app) as client:
        login(client)
        data = {'csrf_token': client.cookies.get('csrf_token'), 'company': 'Synthetic', 'role': 'Support',
                'job_description': 'Support Python and Linux workflows.', 'offer_valid_until': '2026-11-30',
                'llm_provider': 'mock'}
        response = client.post('/analyze', data=data, headers={'Accept': 'application/json'})
        assert response.status_code == 202
        task_id = response.json()['task_id']
        task = app.state.task_manager.get_task(task_id)
        assert task.payload['job']['offer_valid_until'] == '2026-11-30'
        assert 'value="2026-11-30"' in client.get('/?from_task=' + task_id).text
        data['offer_valid_until'] = '2026-12-10'
        other = client.post('/analyze', data=data, headers={'Accept': 'application/json'})
        assert other.status_code == 202
        assert other.json()['task_id'] != task_id
        data['offer_valid_until'] = '2026-02-29'
        assert client.post('/analyze', data=data).status_code == 422


def test_deadline_http_account_isolation(shared_app, monkeypatch, resume_payload):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(shared_app) as client:
        owner, demo = runtimes(shared_app)
        draft, slug, _ = seed(owner.state.storage, resume_payload)
        assert sign_in(client, 'demo').status_code == 303
        # Remove the separate read-only demo guard to exercise account-local lookup itself.
        monkeypatch.setattr(demo.state.settings, 'demo_mode', False)
        for kind, identifier in [('draft', draft), ('application', slug)]:
            response = client.post(f'/offers/{kind}/{identifier}/deadline?account=owner',
                data={'csrf_token': client.cookies.get('csrf_token'), 'offer_valid_until': '2026-12-10'},
                headers={'X-Account': 'owner'}, follow_redirects=False)
            assert response.status_code == 404
        assert owner.state.storage.load_draft(draft)[0].offer_valid_until == date(2026, 11, 30)
