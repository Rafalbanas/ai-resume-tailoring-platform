import asyncio
import threading

import httpx

from app.main import create_app
from app.services.task_manager import TaskKind, TaskStatus
from tests.test_generation_queue import seed, until
from tests.test_resource_limits import login


async def test_browser_export_returns_status_before_cpu_finishes_and_reuses_submission(monkeypatch, resume_payload):
    import app.main as main

    app = create_app(main.get_settings())
    entered, release = threading.Event(), threading.Event()
    calls = []

    def pdf(resume, profile, output, *args, **kwargs):
        calls.append(output)
        entered.set()
        assert release.wait(10)
        output.write_bytes(b'%PDF synthetic')

    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://testserver'
    ) as client:
        await login(client)
        draft = seed(app, resume_payload)
        monkeypatch.setattr(app.state.pdf_generator, 'fit_resume', lambda r, *a, **k: (r, []))
        monkeypatch.setattr(app.state.pdf_generator, 'generate', pdf)
        monkeypatch.setattr(app.state, 'docx_generator', lambda r, p, o, **k: o.write_bytes(b'docx synthetic'))
        data = {'csrf_token': client.cookies.get('csrf_token'), 'background_export': 'true'}
        try:
            response = await asyncio.wait_for(client.post('/generate/' + draft, data=data), 2)
            assert response.status_code == 303
            location = response.headers['location']
            assert location.startswith('/tasks/') and location.endswith('/view')
            identifier = location.split('/')[2]
            task = app.state.task_manager.get_task(identifier)
            assert task.kind == TaskKind.EXPORT and task.keep_history
            assert await asyncio.to_thread(entered.wait, 3)
            assert (await client.get(location)).status_code == 200
            status = await client.get('/tasks/' + identifier)
            assert status.status_code == 200 and status.json()['status'] == 'running'
            assert not status.headers.get_list('set-cookie')
            repeated = await asyncio.wait_for(client.post('/generate/' + draft, data=data), 2)
            assert repeated.headers['location'] == location
            # Queue controls still work while CPU export owns the mutation lock.
            paused = await client.post('/queue/pause', data={'csrf_token': client.cookies.get('csrf_token')})
            assert paused.status_code == 303
            assert app.state.task_manager.activity_for()['paused']
            assert len(calls) == 1
        finally:
            release.set()
        await until(lambda: app.state.task_manager.get_task(identifier).status == TaskStatus.COMPLETED)
        result = app.state.task_manager.get_task(identifier)
        assert result.result['redirect_url'].startswith('/preview/')
        assert (await client.get(location)).headers['location'] == result.result['redirect_url']
        folder = app.state.storage.application_folder(result.result['slug'])
        assert (folder / 'resume.pdf').read_bytes() == b'%PDF synthetic'
        assert (folder / 'resume.docx').read_bytes() == b'docx synthetic'


async def test_background_export_rejects_foreign_origin_and_bad_csrf_before_admission(resume_payload):
    import app.main as main

    app = create_app(main.get_settings())
    async with app.router.lifespan_context(app), httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url='http://testserver'
    ) as client:
        await login(client)
        draft = seed(app, resume_payload)
        data = {'csrf_token': client.cookies.get('csrf_token'), 'background_export': 'true'}
        foreign = await client.post('/generate/' + draft, data=data, headers={'Origin': 'https://foreign.invalid'})
        assert foreign.status_code == 403
        bad = await client.post('/generate/' + draft, data=data | {'csrf_token': 'wrong'})
        assert bad.status_code == 403
        assert not app.state.task_manager.activity_for()['queued_tasks']
        assert not list(app.state.storage.generated_dir.iterdir())
