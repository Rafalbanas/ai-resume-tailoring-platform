"""Persist the exact text rendered in both formats, never a pre-cleanup version."""
import asyncio
import json

import pytest
from starlette.testclient import TestClient

from app.main import app
from app.models.job import JobRequest, MatchLevel
from app.services.draft_export import export_draft
from app.services.resume_export import prepare_resume
from app.services.task_manager import TaskManager


def test_layout_cleanup_is_shared_by_json_pdf_docx_and_confirmation(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app):
        state = app.state
        job = JobRequest(company='Synthetic', role='Support Engineer',
                         job_description='Requirements\nPython automation and Linux support knowledge required.')
        response = asyncio.run(state.providers['mock'].tailor(job, state.profile))
        draft = state.storage.save_draft(job, response)
        rendered = []
        def fit(resume, *args, **kwargs):
            fitted = resume.model_copy(deep=True)
            fitted.professional_summary += ' ' + fitted.professional_summary
            fitted.core_skills += fitted.core_skills[:1]
            return fitted, ['Synthetic layout adjustment']
        def generate(resume, profile, output, *args, **kwargs):
            canonical = prepare_resume(resume, profile)
            rendered.append(canonical.model_dump(mode='json'))
            output.write_bytes(b'synthetic export')
        async def cpu(state, function, *args, **kwargs):
            return function(*args, **kwargs)
        monkeypatch.setattr(state.pdf_generator, 'fit_resume', fit)
        monkeypatch.setattr(state.pdf_generator, 'generate', generate)
        monkeypatch.setattr(state, 'docx_generator', generate)
        monkeypatch.setattr('app.services.draft_export.cpu_work_for_state', cpu)
        slug = asyncio.run(export_draft(state, draft))
        saved = json.loads((state.storage.application_folder(slug) / 'resume.json').read_text())
        assert len(rendered) == 2
        assert saved == rendered[0] == rendered[1]
        # Cleanup is not a user approval; no owner confirmation is fabricated.
        metadata = json.loads((state.storage.application_folder(slug) / 'metadata.json').read_text())
        assert not metadata.get('summary_confirmation')


def test_unreliable_analysis_never_reaches_fit_or_export(monkeypatch):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app):
        state = app.state
        job = JobRequest(company='Synthetic', role='Support Engineer',
                         job_description='Requirements\nPython automation and Linux support knowledge required.')
        response = asyncio.run(state.providers['mock'].tailor(job, state.profile))
        response.analysis.is_reliable = False
        response.analysis.match_level = MatchLevel.UNRELIABLE
        draft = state.storage.save_draft(job, response)
        monkeypatch.setattr(state.pdf_generator, 'fit_resume', lambda *a, **k: pytest.fail('Unreliable analysis must not export'))
        with pytest.raises(ValueError, match='incomplete or unreliable'):
            asyncio.run(export_draft(state, draft, require_reliable_analysis=True))
        assert not list(state.storage.generated_dir.iterdir())
