from pathlib import Path

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


@pytest.mark.asyncio
async def test_nofluff_uses_full_named_sections_instead_of_jsonld_description():
    html = Path("tests/fixtures/nofluff_unix_admin.html").read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract("https://nofluffjobs.com/job/unix-admin-mindbox-krakow")

    assert result.extraction_method == "html"
    assert result.role == "Unix Admin"
    assert result.company == "Mindbox Sp. z o.o."
    assert result.job_description.startswith("MUST HAVE\n")
    for expected in ("5+ years", "RHEL 6–9", "Bash", "Ansible", "YUM/DNF", "performance tuning", "on-call"):
        assert expected in result.job_description
    for noise in ("What you get in return", "Multisport", "technology image"):
        assert noise not in result.job_description


@pytest.mark.asyncio
async def test_justjoin_preserves_technical_sections_and_removes_ui_noise():
    html = Path("tests/fixtures/justjoin_trainee_data_engineer.html").read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract(
        "https://justjoin.it/job-offer/vertex-recruitments-trainee-data-engineer-warszawa-data"
    )

    assert result.extraction_method == "html"
    assert result.role == "Trainee Data Engineer"
    assert result.company == "Vertex Recruitments"
    assert result.job_description
    for expected in (
        "Junior",
        "Remote",
        "JOB DESCRIPTION",
        "Co będziesz robić?",
        "Nasze oczekiwania",
        "TECH STACK",
        "SQL",
        "Python",
        "ETL/ELT",
        "Data Lake",
        "Big Data",
        "Spark",
        "PySpark",
        "Databricks",
        "CI/CD",
        "Docker",
        "Kubernetes",
        "Apache Airflow",
        "Terraform",
        "Infrastructure as Code / IaC",
        "Apache Kafka",
        "English B2",
        "Polish C2",
    ):
        assert expected in result.job_description
    assert any(cloud in result.job_description for cloud in ("AWS", "GCP", "Azure"))
    for noise in (
        "OFFICE LOCATION",
        "Job offers Vertex Recruitments",
        "company profile",
        "Apply",
        "Save",
        "Similar offers",
        "Private medical coverage",
    ):
        assert noise not in result.job_description


@pytest.mark.asyncio
async def test_justjoin_next_payload_uses_full_html_and_jsonld_metadata_fallback():
    html = Path("tests/fixtures/justjoin_platform_engineer_next.html").read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract(
        "https://justjoin.it/job-offer/alois-technologies-spolka-z-oo-platform-engineer-wroclaw-devops"
    )

    assert result.extraction_method == "html"
    assert result.role == "Platform Engineer"
    assert result.company == "ALOIS TECHNOLOGIES SPÓŁKA Z OO"
    for expected in (
        "6+ years",
        "PostgreSQL",
        "Bash",
        "Linux / Unix",
        "Azure Data Factory",
        "GitLab CI/CD",
        "Elasticsearch",
        "Cloudera",
        "Java",
    ):
        assert expected in result.job_description
    for noise in ("Why this one is worth a look", "Competitive daily B2B rate", "Apply today"):
        assert noise not in result.job_description


@pytest.mark.asyncio
async def test_workday_preserves_requirements_and_removes_corporate_boilerplate():
    html = Path("tests/fixtures/workday_windows_automation_engineer.html").read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract(
        "https://motorolasolutions.wd5.myworkdayjobs.com/Careers/job/Krakow-Poland/Windows-Automation-Engineer_R64920"
    )

    assert result.extraction_method == "html"
    assert result.role == "Windows Automation Engineer"
    assert result.company == "Motorola Solutions"
    assert result.job_description
    for expected in (
        "Krakow, Poland",
        "R64920",
        "DEPARTMENT OVERVIEW",
        "JOB DESCRIPTION",
        "RESPONSIBILITIES",
        "BASIC REQUIREMENTS",
        "WHAT YOU NEED TO SUCCEED",
        "BONUS POINTS IF YOU HAVE",
        "Windows Server",
        "Windows Client OS",
        "Active Directory",
        "automated installation and configuration",
        "automation",
        "programming/scripting concepts",
        "variables",
        "control structures",
        "loops",
        "error handling",
        "Python",
        "Bash",
        "PowerShell",
        "Git",
        "CI/CD",
        "Agile",
        "TCP/IP",
        "TLS",
        "PKI",
    ):
        assert expected in result.job_description
    for noise in (
        "Company Overview",
        "Competitive salary package",
        "Private medical coverage",
        "Employee Pension Plan",
        "Life insurance",
        "Employee Stock Purchase Plan",
        "parking",
        "volleyball",
        "grill",
        "wellness benefits",
        "Travel Requirements",
        "Relocation Provided",
        "Position Type",
        "Referral Payment Plan",
        "EEO Statement",
        "equal opportunity employer",
    ):
        assert noise not in result.job_description
