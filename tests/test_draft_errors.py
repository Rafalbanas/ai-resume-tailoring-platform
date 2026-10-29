from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.templating import Jinja2Templates
from starlette.requests import Request

from app.routes import web
from app.services.storage import Storage


@pytest.mark.asyncio
@pytest.mark.parametrize("missing,status", [(True, 404), (False, 422)])
@pytest.mark.parametrize("endpoint", ["analysis", "generate"])
async def test_draft_errors_show_recovery_page(tmp_path, monkeypatch, missing, status, endpoint):
    app = FastAPI()
    app.state.storage = Storage(tmp_path)
    app.state.settings = SimpleNamespace(csrf_cookie_name="csrf", csrf_secret="secret")
    app.state.templates = Jinja2Templates(directory=Path(__file__).resolve().parents[1] / "templates")
    monkeypatch.setattr(web, "guard", lambda _: None)
    monkeypatch.setattr(web, "limit_request", lambda _: None)
    monkeypatch.setattr(web, "validate_csrf", lambda *args: None)
    monkeypatch.setattr(web, "context", lambda request, **values: {"request": request, "app_root_path": "/demo", **values})
    draft_id = "a" * 32
    if not missing:
        (app.state.storage.drafts_dir / f"{draft_id}.json").write_text('{"response": null}')
    request = Request({"type": "http", "method": "GET", "path": "/analysis/" + draft_id,
                       "headers": [], "app": app, "root_path": "/demo"})
    if endpoint == "analysis":
        response = await web.analysis_view(request, draft_id)
    else:
        response = await web.generate(request, draft_id, csrf_token="test")
    assert response.status_code == status
    assert "text/html" in response.headers["content-type"]
    assert b'href="/demo/history"' in response.body
    assert b'href="/demo/"' in response.body
    assert (b"Draft not found" in response.body) == missing
