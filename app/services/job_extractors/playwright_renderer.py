import asyncio
import os
import sys
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from starlette.concurrency import run_in_threadpool

from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.security import PublicUrlGuard


class BrowserRenderError(RuntimeError):
    pass


@dataclass(slots=True)
class RenderedPage:
    url: str
    html: str


class SafePlaywrightRenderer:
    def __init__(self, guard: PublicUrlGuard, timeout_seconds: float, max_bytes: int, max_redirects: int, *, isolated: bool = True):
        self.isolated = isolated
        self.slots = asyncio.Semaphore(1)
        self.guard = guard
        self.timeout_ms = int(timeout_seconds * 1000)
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    async def render(self, url: str) -> RenderedPage:
        if self.slots.locked():
            raise BrowserRenderError('Browser processing is busy')
        async with self.slots:
            try:
                async with asyncio.timeout(self.timeout_ms / 1000 + 5):
                    return await self._render(url)
            except TimeoutError as exc:
                raise BrowserRenderError('Browser processing exceeded its deadline') from exc

    async def _render(self, url: str) -> RenderedPage:
        from app.services.processing import ENDPOINT
        endpoint = ENDPOINT.get()
        if self.isolated and (endpoint[0] if endpoint is not None else os.environ.get('PROCESSING_URL')):
            from app.services.processing import ProcessingError, process
            try:
                value = await run_in_threadpool(process, 'browser', {'url': url, 'timeout': self.timeout_ms / 1000,
                    'max_bytes': self.max_bytes, 'max_redirects': self.max_redirects}, timeout=self.timeout_ms / 1000 + 5)
                return RenderedPage(**value)
            except ProcessingError as exc:
                raise BrowserRenderError('Browser processing is unavailable') from exc
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserRenderError("Playwright is unavailable") from exc

        await self.guard.validate(url)
        navigation_requests = 0
        requests_remaining = 32
        bytes_remaining = self.max_bytes * 4
        try:
            from app.services.processing import clean_environment
            async with async_playwright() as playwright, _browser_launcher(playwright.chromium.executable_path) as launcher:
                browser = await playwright.chromium.launch(
                    headless=True, executable_path=str(launcher), env={**clean_environment(), "HOME": str(launcher.parent), "TMPDIR": str(launcher.parent)},
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
                context = await browser.new_context(java_script_enabled=True, service_workers="block")
                await context.route_web_socket("**/*", lambda ws: ws.close())
                page = await context.new_page()

                async def secure_route(route):
                    nonlocal navigation_requests, requests_remaining, bytes_remaining
                    requests_remaining -= 1
                    if requests_remaining < 0 or bytes_remaining <= 0:
                        await route.abort()
                        return
                    request = route.request
                    if request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                        return
                    if request.is_navigation_request():
                        navigation_requests += 1
                        if navigation_requests > self.max_redirects + 1:
                            await route.abort()
                            return
                    if not request.url.startswith(("https://", "http://")):
                        await route.abort()
                        return
                    try:
                        fetcher = SafeHttpFetcher(self.timeout_ms / 1000, self.max_bytes, self.max_redirects, guard=self.guard)
                        fetched = await fetcher.fetch(request.url, html_only=False)
                        bytes_remaining -= len(fetched.html.encode())
                        if bytes_remaining < 0:
                            await route.abort()
                            return
                        await route.fulfill(status=200, content_type=fetched.content_type, body=fetched.html)
                    except Exception:
                        await route.abort()
                        return
                    # Routed HTTP(S) requests use the address-pinned fetcher.

                # Page routes miss the first request of popup windows. Apply
                # the same address-pinned policy to every page in this context.
                await context.route("**/*", secure_route)
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_timeout(1500)
                await self.guard.validate(page.url)
                html = await page.content()
                final_url = page.url
                await browser.close()
        except Exception as exc:
            raise BrowserRenderError("Could not render job page") from exc
        if len(html.encode("utf-8")) > self.max_bytes:
            raise BrowserRenderError("Rendered page is too large")
        return RenderedPage(final_url, html)




@asynccontextmanager
async def _browser_launcher(executable):
    # Chromium has no native IP sockets, even if a route interception is missed.
    # Validated HTTP runs in the trusted Python fetcher, supplied via route.fulfill.
    with tempfile.TemporaryDirectory(prefix='cvtailor-browser-') as directory:
        path = Path(directory) / 'chromium'
        root = str(Path(__file__).resolve().parents[3])
        path.write_text(f"#!{sys.executable}\nimport sys,os\nsys.path.insert(0,{root!r})\n"
                        "from app.services.processing_security import restrict_network\nrestrict_network()\n"
                        f"os.execv({executable!r},[{executable!r},*sys.argv[1:]])\n")
        path.chmod(0o700)
        yield path
