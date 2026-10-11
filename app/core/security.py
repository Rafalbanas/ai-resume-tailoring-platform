import hashlib
import hmac
import secrets
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request


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


def require_session(request: Request) -> None:
    if not getattr(request.state, "authenticated", False):
        raise HTTPException(status_code=401, detail="Authentication required")


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
