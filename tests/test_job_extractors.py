import httpx
import pytest

from app.core.config import Settings
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.generic import GenericHtmlExtractor
from app.services.job_extractors.jsonld import JsonLdExtractor
from app.services.job_extractors.security import PublicUrlGuard, UnsafeUrlError


async def public_resolver(hostname: str, port: int) -> list[str]:
    return ["93.184.216.34"]


async def private_resolver(hostname: str, port: int) -> list[str]:
    return ["10.10.0.5"]


def test_jsonld_job_posting_is_preferred():
    html = """
    <script type="application/ld+json">
      {"@context":"https://schema.org","@type":"JobPosting","title":"Platform Engineer",
       "hiringOrganization":{"@type":"Organization","name":"Acme"},
       "description":"<p>Build reliable platforms.</p><p>Operate Kubernetes and Python services.</p>"}
    </script>
    """
    result = JsonLdExtractor().extract(html)
    assert result.company == "Acme"
    assert result.role == "Platform Engineer"
    assert "Operate Kubernetes" in result.job_description


def test_generic_html_removes_navigation_and_cookie_noise():
    html = """
    <html><body><nav>Jobs About Contact</nav><div class="cookie-consent">Accept cookies</div>
    <main><h1>Site Reliability Engineer</h1><div class="company-name">Example Ltd</div>
    <section id="job-description"><h2>Your role</h2><p>Maintain reliable cloud systems and automate
    production operations with Python. Work with the engineering team to improve observability.</p></section>
    <section class="related-jobs">Other roles marketing text</section></main><footer>Legal</footer></body></html>
    """
    result = GenericHtmlExtractor().extract(html)
    assert result.role == "Site Reliability Engineer"
    assert result.company == "Example Ltd"
    assert "Maintain reliable cloud systems" in result.job_description
    assert "Accept cookies" not in result.job_description
    assert "Other roles marketing" not in result.job_description


@pytest.mark.asyncio
async def test_unsupported_site_uses_generic_html_fallback():
    html = """<main><h1>Backend Engineer</h1><div class="company-name">Unknown Co</div>
    <article id="job-description">Design and maintain backend services using Python. Improve reliability,
    testing, monitoring, deployment automation, and operational documentation across the platform.</article></main>"""

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract("https://jobs.example.test/backend")
    assert result.extraction_method == "html"
    assert result.company == "Unknown Co"
    assert result.role == "Backend Engineer"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://localhost/admin",
        "http://127.0.0.1:8000/health",
        "http://[::1]/",
        "http://169.254.169.254/latest/meta-data/",
        "http://metadata.google.internal/",
    ],
)
async def test_ssrf_targets_are_rejected(url):
    with pytest.raises(UnsafeUrlError):
        await PublicUrlGuard(public_resolver).validate(url)


@pytest.mark.asyncio
async def test_hostname_resolving_to_private_ip_is_rejected():
    with pytest.raises(UnsafeUrlError):
        await PublicUrlGuard(private_resolver).validate("https://jobs.example.test/role")


@pytest.mark.asyncio
async def test_timeout_returns_manual_fallback():
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        0.1, 100_000, 1, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract("https://jobs.example.test/slow")
    assert result.extraction_method == "manual_required"
    assert result.job_description == ""
