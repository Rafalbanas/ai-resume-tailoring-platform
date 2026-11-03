"""New exports must not publish partial documents on failure/cancellation."""
import asyncio
import stat

import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

from app.main import app
from app.models.job import JobRequest
from app.services.draft_export import export_draft
from app.services.storage import Storage
from app.services.task_manager import TaskManager


@pytest.mark.parametrize('failure', ['pdf', 'docx', 'quota', 'mark', 'cancel', 'metadata', 'publish', None])
def test_export_stages_both_artifacts_and_rolls_back_new_application(monkeypatch, failure):
    monkeypatch.setattr(TaskManager, 'start_worker', lambda *args: None)
    with TestClient(app):
        state = app.state
        job = JobRequest(company='Synthetic', role='Support Engineer',
                         job_description='Requirements\nPython automation and Linux support knowledge required.')
        response = asyncio.run(state.providers['mock'].tailor(job, state.profile))
        draft = state.storage.save_draft(job, response)
        existing = state.storage.generated_dir / 'existing-cv'
        existing.mkdir()
        (existing / 'sentinel').write_bytes(b'original')
        visible_before_render = []

        def fit(resume, *args, **kwargs):
            return resume, []

        def pdf(resume, profile, path, *args, **kwargs):
            assert path.parent.name.startswith('.export-')
            assert list(state.storage.generated_dir.glob('*/metadata.json')) == visible_before_render
            path.write_bytes(b'%PDF synthetic')
            if failure == 'pdf':
                raise OSError('synthetic PDF failure')

        def docx(resume, profile, path, *args, **kwargs):
            assert path.parent.name.startswith('.export-')
            path.write_bytes(b'PK synthetic')
            if failure == 'docx':
                raise OSError('synthetic DOCX failure')
            if failure == 'cancel':
                raise asyncio.CancelledError()

        calls = []

        def quota():
            calls.append(True)
            if failure == 'quota' and len(calls) == 2:
                raise HTTPException(507, 'synthetic post-render quota')

        async def cpu(state, function, *args, **kwargs):
            return function(*args, **kwargs)

        monkeypatch.setattr(state.pdf_generator, 'fit_resume', fit)
        monkeypatch.setattr(state.pdf_generator, 'generate', pdf)
        monkeypatch.setattr(state, 'docx_generator', docx)
        monkeypatch.setattr(state.resource_budget, 'check_disk', quota)
        monkeypatch.setattr('app.services.draft_export.cpu_work_for_state', cpu)
        if failure == 'mark':
            def mark(*args):
                raise OSError('synthetic metadata failure')
            monkeypatch.setattr(state.storage, 'mark_export_checked', mark)
        if failure == 'metadata':
            original = Storage.save_application

            def save(storage, *args, **kwargs):
                original(storage, *args, **kwargs)
                raise OSError('synthetic metadata write failure')

            monkeypatch.setattr(Storage, 'save_application', save)
        if failure == 'publish':
            import app.services.draft_export as exporter
            original_replace = exporter.os.replace

            def replace(source, destination):
                if source.is_dir():
                    raise OSError('synthetic directory publication failure')
                return original_replace(source, destination)

            monkeypatch.setattr(exporter.os, 'replace', replace)

        if failure:
            with pytest.raises((OSError, HTTPException, asyncio.CancelledError)):
                asyncio.run(export_draft(state, draft))
            assert list(state.storage.generated_dir.iterdir()) == [existing]
        else:
            slug = asyncio.run(export_draft(state, draft))
            folder = state.storage.application_folder(slug)
            assert stat.S_IMODE(folder.stat().st_mode) == 0o700
            assert (folder / 'resume.pdf').read_bytes() == b'%PDF synthetic'
            assert (folder / 'resume.docx').read_bytes() == b'PK synthetic'
            assert len(calls) == 3
            assert not list(state.storage.generated_dir.glob('.export-*'))
            visible_before_render[:] = list(state.storage.generated_dir.glob('*/metadata.json'))
            second_slug = asyncio.run(export_draft(state, draft))
            assert second_slug != slug
            assert state.storage.application_folder(second_slug).is_dir()
            assert (folder / 'resume.pdf').read_bytes() == b'%PDF synthetic'
        assert (existing / 'sentinel').read_bytes() == b'original'
        assert state.storage.load_draft(draft)[0].company == 'Synthetic'
