import asyncio
import threading
from types import SimpleNamespace

import httpx
import pytest
from fastapi import HTTPException

from app.main import create_app
from app.services.processing import cpu_work
from app.services.resource_budget import ResourceBudget
from tests.test_provider_fallback import job, sample_workflow_response
from tests.test_resource_limits import login


def seed(app, resume_payload, index=0):
    from app.models.resume import TailoredResume

    response = sample_workflow_response("mock", "fixture")
    response.resume = TailoredResume.model_validate(resume_payload)
    return app.state.storage.save_draft(job().model_copy(update={"company": f"Example {index}"}), response)


async def until(predicate):
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.005)


async def test_parallel_exports_wait_and_save_each_documents_without_holding_upload_slots(monkeypatch, resume_payload):
    import app.main as main

    app = create_app(main.get_settings())
    entered, release = threading.Event(), threading.Event()
    active = 0

    def pdf(resume, profile, output, *args, **kwargs):
        nonlocal active
        active += 1
        assert active == 1
        entered.set()
        assert release.wait(5)
        output.write_bytes(b"%PDF " + output.parent.name.encode())
        active -= 1

    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await login(client)
        drafts = [seed(app, resume_payload, i) for i in range(3)]
        monkeypatch.setattr(app.state.pdf_generator, "fit_resume", lambda r, *a, **k: (r, []))
        monkeypatch.setattr(app.state.pdf_generator, "generate", pdf)
        monkeypatch.setattr(
            app.state, "docx_generator", lambda r, p, o, **k: o.write_bytes(b"docx " + o.parent.name.encode())
        )
        tasks = [
            asyncio.create_task(
                client.post("/generate/" + draft, data={"csrf_token": client.cookies.get("csrf_token")})
            )
            for draft in drafts
        ]
        try:
            assert await asyncio.to_thread(entered.wait, 2)
            await until(lambda: app.state.resource_budget.generation_slots._value == 1)
            assert not any(t.done() for t in tasks)
            assert app.state.resource_budget.body_slots._value == 2
            assert (await asyncio.wait_for(client.get("/health"), 1)).status_code == 200
        finally:
            release.set()
        responses = await asyncio.wait_for(asyncio.gather(*tasks), 5)
        assert all(r.status_code == 303 for r in responses)
        assert len({r.headers["location"] for r in responses}) == 3
        for i, response in enumerate(responses):
            slug = response.headers["location"].rsplit("/", 1)[1]
            saved = app.state.storage.load_application(slug)
            assert saved[0].company == f"Example {i}"
            folder = app.state.storage.application_folder(slug)
            assert (folder / "resume.pdf").read_bytes() == b"%PDF " + slug.encode()
            assert (folder / "resume.docx").read_bytes() == b"docx " + slug.encode()
        assert app.state.resource_budget.generation_slots._value == 4
        assert app.state.resource_budget.mutation_slots._value == 1


@pytest.mark.parametrize("cancel", [True, False])
async def test_cancelled_or_timed_out_generation_releases_its_queue_place(monkeypatch, resume_payload, cancel):
    import app.main as main

    app = create_app(main.get_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await login(client)
        draft = seed(app, resume_payload)
        budget = app.state.resource_budget
        await budget.mutation_slots.acquire()
        if not cancel:
            monkeypatch.setattr(main, "GENERATION_WAIT_SECONDS", 0.03)
        pending = asyncio.create_task(
            client.post(
                "/generate/" + draft,
                data={"csrf_token": client.cookies.get("csrf_token")},
                headers={"Accept": "text/html"},
            )
        )
        try:
            await until(lambda: budget.generation_slots._value == 3)
            if cancel:
                pending.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await pending
            else:
                result = await pending
                assert result.status_code == 303
                assert result.headers["location"] == f"/analysis/{draft}?export_busy=1"
                assert result.headers["retry-after"] == "5"
            assert budget.generation_slots._value == 4
            assert budget.mutation_slots.locked()
            assert budget.body_slots._value == 2
            assert not list(app.state.storage.generated_dir.iterdir())
        finally:
            budget.mutation_slots.release()


async def test_invalid_csrf_is_rejected_before_waiting_for_account_lock(resume_payload):
    import app.main as main

    app = create_app(main.get_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await login(client)
        draft = seed(app, resume_payload)
        await app.state.resource_budget.mutation_slots.acquire()
        try:
            result = await asyncio.wait_for(client.post("/generate/" + draft, data={"csrf_token": "wrong"}), 1)
            assert result.status_code == 403
            assert app.state.resource_budget.generation_slots._value == 4
        finally:
            app.state.resource_budget.mutation_slots.release()


async def test_full_generation_queue_returns_browser_to_its_draft(resume_payload):
    import app.main as main

    app = create_app(main.get_settings())
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client,
    ):
        await login(client)
        draft = seed(app, resume_payload)
        slots = app.state.resource_budget.generation_slots
        for _ in range(4):
            await slots.acquire()
        try:
            response = await client.post(
                "/generate/" + draft,
                data={"csrf_token": client.cookies.get("csrf_token")},
                headers={"Accept": "text/html"},
            )
            assert response.status_code == 303
            page = await client.get(response.headers["location"])
            assert page.status_code == 200 and "Your draft is saved" in page.text
            assert slots._value == 0
        finally:
            for _ in range(4):
                slots.release()


async def test_cpu_processing_waits_for_preview_and_releases_cancelled_waiter(tmp_path):
    budget = ResourceBudget(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resource_budget=budget)))
    await budget.cpu_slots.acquire()
    called = []
    pending = asyncio.create_task(cpu_work(request, lambda: called.append("complete")))
    await until(lambda: budget.cpu_queue_slots._value == 3)
    assert not called and not pending.done()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert budget.cpu_queue_slots._value == 4 and budget.cpu_slots.locked()
    next_call = asyncio.create_task(cpu_work(request, lambda: called.append("complete")))
    await until(lambda: budget.cpu_queue_slots._value == 3)
    budget.cpu_slots.release()
    await next_call
    assert called == ["complete"] and budget.cpu_queue_slots._value == 4
    assert budget.cpu_slots._value == 1


async def test_cpu_queue_is_bounded_and_times_out_without_leaking_slots(tmp_path, monkeypatch):
    import app.services.processing as processing

    budget = ResourceBudget(tmp_path)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(resource_budget=budget)))
    for _ in range(4):
        await budget.cpu_queue_slots.acquire()
    with pytest.raises(HTTPException, match="queue is full"):
        await cpu_work(request, lambda: None)
    for _ in range(4):
        budget.cpu_queue_slots.release()
    await budget.cpu_slots.acquire()
    monkeypatch.setattr(processing, "CPU_QUEUE_WAIT_SECONDS", 0.01)
    with pytest.raises(HTTPException, match="busy"):
        await cpu_work(request, lambda: None)
    assert budget.cpu_queue_slots._value == 4 and budget.cpu_slots.locked()
    budget.cpu_slots.release()
