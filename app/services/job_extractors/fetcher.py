import asyncio
from dataclasses import dataclass
from urllib.parse import urljoin

import httpx

from app.services.job_extractors.security import PublicUrlGuard

USER_AGENT = "CVTailor/1.0 (+single user-requested job extraction)"
# The Protocol redirects unrecognized clients to an unsupported-browser page.
# Keep our product identifier while supplying its required browser tokens.
THEPROTOCOL_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0.0.0 Safari/537.36 " + USER_AGENT
)


class JobFetchError(RuntimeError):
    pass


@dataclass(slots=True)
class FetchedPage:
    url: str
    html: str
    content_type: str = "text/html"


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

    async def fetch(self, url: str, *, html_only: bool = True) -> FetchedPage:
        try:
            async with asyncio.timeout(self.timeout_seconds):
                return await self._fetch(url, html_only=html_only)
        except TimeoutError as exc:
            raise JobFetchError('Job fetch exceeded its deadline') from exc

    async def _fetch(self, url: str, *, html_only: bool = True) -> FetchedPage:
        current_url = url
        timeout = httpx.Timeout(self.timeout_seconds, connect=min(self.timeout_seconds, 5.0))
        headers = {
            "User-Agent": USER_AGENT,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "identity",
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
                    addresses = await self.guard.resolve_public(current_url)
                    original = httpx.URL(current_url)
                    address = next((value for value in addresses if ":" not in value), addresses[0])
                    pinned = original.copy_with(host=address)
                    hostname = original.host.lower().rstrip(".")
                    user_agent = THEPROTOCOL_USER_AGENT if (
                        hostname == "theprotocol.it" or hostname.endswith(".theprotocol.it")
                    ) else USER_AGENT
                    # Connect to the already validated address; retain Host and
                    # certificate verification/SNI for the original hostname.
                    async with client.stream("GET", pinned,
                                             headers={"Host": original.netloc.decode("ascii"), "User-Agent": user_agent},
                                             extensions={"sni_hostname": original.host}) as response:
                        if response.is_redirect:
                            location = response.headers.get("location")
                            if not location or redirect_number >= self.max_redirects:
                                raise JobFetchError("Too many or invalid redirects")
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        if response.headers.get('content-encoding', 'identity').lower() not in {'', 'identity'}:
                            raise JobFetchError('Compressed job responses are not accepted')
                        content_type = response.headers.get("content-type", "").lower()
                        if html_only and content_type and not any(value in content_type for value in ("text/html", "application/xhtml+xml")):
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
                        return FetchedPage(current_url, b"".join(chunks).decode(encoding, errors="replace"), content_type or "text/html")
        except (httpx.HTTPError, TimeoutError, UnicodeError) as exc:
            raise JobFetchError("Could not fetch job page") from exc
        raise JobFetchError("Could not fetch job page")
