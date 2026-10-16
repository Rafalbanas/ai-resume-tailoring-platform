"""Keep application behavior; serialize deployment drain with mutating requests."""

import fcntl
import os
import sys
from pathlib import Path

import uvicorn
from starlette.responses import JSONResponse


class DeploymentAdmission:
    def __init__(self, app, data_dir):
        self.app = app
        self.path = Path(data_dir) / ".deployment-admission.lock"

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}:
            return await self.app(scope, receive, send)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                response = JSONResponse({"detail": "Deployment in progress. Please retry shortly."}, status_code=503, headers={"Retry-After": "30"})
                return await response(scope, receive, send)
            return await self.app(scope, receive, send)
        finally:
            os.close(descriptor)


if __name__ == "__main__":
    sys.path.insert(0, "/app")
    from app.main import app

    app.add_middleware(DeploymentAdmission, data_dir=os.environ["DATA_DIR"])
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("CVTAILOR_PORT", "18000")),
        root_path=os.environ.get("APP_ROOT_PATH", ""),
        proxy_headers=True,
        forwarded_allow_ips="127.0.0.1",
    )
