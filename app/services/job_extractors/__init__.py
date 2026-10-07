import logging

from app.core.config import Settings
from app.models.job import JobExtraction
from app.services.job_extractors.base import BaseExtractor, ExtractionCandidate
from app.services.job_extractors.fetcher import JobFetchError, SafeHttpFetcher
from app.services.job_extractors.generic import GenericHtmlExtractor
from app.services.job_extractors.jsonld import JsonLdExtractor
from app.services.job_extractors.justjoin import JustJoinExtractor
from app.services.job_extractors.nofluff import NoFluffExtractor
from app.services.job_extractors.playwright_renderer import BrowserRenderError, SafePlaywrightRenderer
from app.services.job_extractors.pracuj import PracujExtractor
from app.services.job_extractors.security import UnsafeUrlError
from app.services.job_extractors.workday import WorkdayExtractor

logger = logging.getLogger(__name__)


class JobExtractorService:
    def __init__(self, settings: Settings):
        self.max_description_chars = settings.max_job_description_chars
        self.fetcher = SafeHttpFetcher(
            timeout_seconds=settings.job_fetch_timeout_seconds,
            max_bytes=settings.job_fetch_max_bytes,
            max_redirects=settings.job_fetch_max_redirects,
        )
        self.playwright_enabled = settings.job_fetch_playwright_enabled
        self.renderer = SafePlaywrightRenderer(
            guard=self.fetcher.guard,
            timeout_seconds=settings.job_fetch_timeout_seconds,
            max_bytes=settings.job_fetch_max_bytes,
            max_redirects=settings.job_fetch_max_redirects,
        )
        self.jsonld = JsonLdExtractor()
        self.adapters: tuple[BaseExtractor, ...] = (
            JustJoinExtractor(),
            NoFluffExtractor(),
            WorkdayExtractor(),
            PracujExtractor(),
        )
        self.generic = GenericHtmlExtractor()

    def _extract_html(self, url: str, html: str) -> tuple[ExtractionCandidate, str]:
        structured = self.jsonld.extract(html)
        if structured.usable:
            return structured, "jsonld"
        adapter = next((candidate for candidate in self.adapters if candidate.matches(url)), None)
        extracted = adapter.extract(html) if adapter else self.generic.extract(html)
        if not extracted.usable and adapter:
            extracted = self.generic.extract(html)
        return extracted, "html"

    def _result(self, candidate: ExtractionCandidate, source: str, method: str) -> JobExtraction:
        return JobExtraction(
            company=candidate.company[:150],
            role=candidate.role[:150],
            job_description=candidate.job_description[: self.max_description_chars],
            source=source,
            extraction_method=method,
        )

    async def extract(self, url: str) -> JobExtraction:
        source = url
        try:
            page = await self.fetcher.fetch(url)
            source = page.url
            candidate, method = self._extract_html(page.url, page.html)
            if candidate.usable:
                return self._result(candidate, source, method)
        except UnsafeUrlError:
            return JobExtraction(source=url, extraction_method="manual_required")
        except JobFetchError:
            logger.info("Static job page fetch failed", extra={"stage": "job_fetch"})

        if self.playwright_enabled:
            try:
                page = await self.renderer.render(url)
                source = page.url
                candidate, _ = self._extract_html(page.url, page.html)
                if candidate.usable:
                    return self._result(candidate, source, "playwright")
            except (UnsafeUrlError, BrowserRenderError):
                logger.info("Browser job page extraction failed", extra={"stage": "job_fetch_browser"})
        return JobExtraction(source=source, extraction_method="manual_required")


__all__ = ["JobExtractorService"]
