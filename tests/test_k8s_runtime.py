import asyncio
import fcntl
import os
import runpy
from pathlib import Path

import httpx
import pytest
from starlette.responses import JSONResponse

DeploymentAdmission = runpy.run_path(str(Path(__file__).resolve().parents[1] / "deploy/k8s/production/runtime.py"))["DeploymentAdmission"]


@pytest.mark.asyncio
async def test_drain_serializes_inflight_writes_but_keeps_reads_available(tmp_path):
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def application(scope, receive, send):
        if scope["method"] == "POST":
            entered.set()
            await finish.wait()
        await JSONResponse({"status": "ok"})(scope, receive, send)

    app = DeploymentAdmission(application, tmp_path)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
        pending = asyncio.create_task(client.post("/analyze"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        descriptor = os.open(tmp_path / ".deployment-admission.lock", os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            finish.set()
            assert (await pending).status_code == 200
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            assert (await client.post("/tasks/example/retry")).status_code == 503
            assert (await client.post("/compare")).status_code == 503
            assert (await client.get("/health")).status_code == 200
            assert (await client.post("/analyze")).headers["retry-after"] == "30"
        finally:
            os.close(descriptor)
        assert (await client.post("/analyze")).status_code == 200
