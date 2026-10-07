import base64
import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request, status


class FixedWindowLimiter:
    def __init__(self, limit: int, window_seconds: int = 60):
        self.limit = limit
        self.window_seconds = window_seconds
        self.hits: dict[str, deque[float]] = defaultdict(deque)

    def check(self, key: str) -> None:
        now = time.monotonic()
        bucket = self.hits[key]
        while bucket and bucket[0] < now - self.window_seconds:
            bucket.popleft()
        if len(bucket) >= self.limit:
            raise HTTPException(status_code=429, detail="Too many requests. Try again shortly.")
        bucket.append(now)


def require_basic_auth(request: Request) -> None:
    header = request.headers.get("authorization", "")
    if not header.startswith("Basic "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Basic realm=CV Tailor"},
        )
    try:
        raw = base64.b64decode(header[6:], validate=True).decode("utf-8")
        username, password = raw.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        username, password = "", ""
    valid = request.app.state.auth_store.verify(username, password)
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic realm=CV Tailor"},
        )


def new_csrf_token(secret: str) -> str:
    nonce = secrets.token_urlsafe(24)
    signature = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    return f"{nonce}.{signature}"


def validate_csrf(token: str, cookie: str, secret: str) -> None:
    if not token or not cookie or not secrets.compare_digest(token, cookie):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
    try:
        nonce, signature = token.rsplit(".", 1)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Invalid CSRF token") from exc
    expected = hmac.new(secret.encode(), nonce.encode(), hashlib.sha256).hexdigest()
    if not secrets.compare_digest(signature, expected):
        raise HTTPException(status_code=403, detail="Invalid CSRF token")
