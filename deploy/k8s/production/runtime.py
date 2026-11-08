"""Serialize deployment drain with mutations; cancellation retains app auth/CSRF."""

import fcntl
import os
import re
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

        # Normalize path for root_path awareness
        root_path = scope.get("root_path", "")
        path = scope["path"]
        if root_path and path.startswith(f"{root_path}/"):
            path = path[len(root_path):]

        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            try:
                fcntl.flock(descriptor, fcntl.LOCK_SH | fcntl.LOCK_NB)
            except BlockingIOError:
                # Exception for specific transport skip paths
                allowed_cancel_paths = [
                    r"/api/v1/batches/[0-9a-f]{32}/cancel",
                    r"/queue/tasks/[0-9a-f]{32}/cancel-batch",
                ]
                is_bypass = scope["method"] == "POST" and any(re.fullmatch(p, path) for p in allowed_cancel_paths)

                if is_bypass:
                    return await self.app(scope, receive, send)

                response = JSONResponse(
                    {
                        "code": "deployment_in_progress",
                        "detail": "Deployment in progress. Existing tasks continue; new operations are temporarily blocked. Cancel remaining offers from the batch status page or retry after deployment.",
                    },
                    status_code=503,
                    headers={"Retry-After": "30", "Cache-Control": "no-store"},
                )
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
