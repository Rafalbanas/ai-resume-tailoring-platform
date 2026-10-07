from dataclasses import dataclass

from app.services.job_extractors.security import PublicUrlGuard


class BrowserRenderError(RuntimeError):
    pass


@dataclass(slots=True)
class RenderedPage:
    url: str
    html: str


class SafePlaywrightRenderer:
    def __init__(self, guard: PublicUrlGuard, timeout_seconds: float, max_bytes: int, max_redirects: int):
        self.guard = guard
        self.timeout_ms = int(timeout_seconds * 1000)
        self.max_bytes = max_bytes
        self.max_redirects = max_redirects

    async def render(self, url: str) -> RenderedPage:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserRenderError("Playwright is unavailable") from exc

        await self.guard.validate(url)
        navigation_requests = 0
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--disable-dev-shm-usage", "--no-sandbox"],
                )
                context = await browser.new_context(java_script_enabled=True)
                page = await context.new_page()

                async def secure_route(route):
                    nonlocal navigation_requests
                    request = route.request
                    if request.resource_type in {"image", "media", "font"}:
                        await route.abort()
                        return
                    if request.is_navigation_request():
                        navigation_requests += 1
                        if navigation_requests > self.max_redirects + 1:
                            await route.abort()
                            return
                    if request.url.startswith(("data:", "blob:", "about:")):
                        await route.continue_()
                        return
                    try:
                        await self.guard.validate(request.url)
                    except Exception:
                        await route.abort()
                        return
                    await route.continue_()

                await page.route("**/*", secure_route)
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
