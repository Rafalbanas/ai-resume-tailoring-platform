from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.services.job_extractors.security import PublicUrlGuard


class JobFetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchedPage:
    url: str
    html: str


class SafeHttpFetcher:
    def __init__(
        self,
        timeout_seconds: float,
        max_bytes: int,
        max_redirects: int,
        guard: PublicUrlGuard | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects
        self.guard = guard or PublicUrlGuard()
        self.transport = transport

    async def fetch(self, url: str) -> FetchedPage:
        current_url = url
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 5.0))
        headers = {
            "User-Agent": "CVTailor/1.0 (+single user-requested job extraction)",
            "Accept": "text/html,application/xhtml+xml",
        }
        try:
            async with httpx.AsyncClient(
                timeout=timeout,
                follow_redirects=False,
                trust_env=False,
                transport=self.transport,
                headers=headers,
            ) as client:
                for redirect_number in range(self.max_redirects + 1):
                    await self.guard.validate(current_url)
                    async with client.stream("GET", current_url) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_number >= self.max_redirects:
                                raise JobFetchError("Too many or invalid redirects")
                            current_url = urljoin(str(response.url), location)
                            continue
                        response.raise_for_status()
                        content_type = response.headers.get("content-type", "").lower()
                        if content_type and not any(value in content_type for value in ("text/html", "application/xhtml+xml")):
                            raise JobFetchError("URL did not return HTML")
                        declared_size = response.headers.get("content-length")
                        if declared_size:
                            try:
                                if int(declared_size) > self.max_bytes:
                                    raise JobFetchError("Response is too large")
                            except ValueError as exc:
                                raise JobFetchError("Invalid response size") from exc
                        chunks: list[bytes] = []
                        size = 0
                        async for chunk in response.aiter_bytes():
                            size += len(chunk)
                            if size > self.max_bytes:
                                raise JobFetchError("Response is too large")
                            chunks.append(chunk)
                        encoding = response.encoding or "utf-8"
                        return FetchedPage(str(response.url), b"".join(chunks).decode(encoding, errors="replace"))
        except (httpx.HTTPError, TimeoutError, UnicodeError) as exc:
            raise JobFetchError("Could not fetch job page") from exc
        raise JobFetchError("Could not fetch job page")
