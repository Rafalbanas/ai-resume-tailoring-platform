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


@pytest.mark.parametrize("noise_class", ["cookie-consent", "related-jobs", "newsletter"])
def test_generic_html_removes_nested_noise_without_reading_decomposed_children(noise_class):
    html = f"""<main><h1>Support Engineer</h1>
    <section id="job-description"><p>Investigate API failures using logs and SQL queries.
    Own support tickets and work with engineering teams to resolve production issues.</p></section>
    <div class="{noise_class}"><div><span>Unwanted content</span></div></div></main>"""

    result = GenericHtmlExtractor().extract(html)

    assert result.usable
    assert "Investigate API failures" in result.job_description
    assert "Unwanted content" not in result.job_description


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
    assert result.job_description.startswith("PORTAL TECHNOLOGY TAGS\n")
    for expected in ("5+ years", "RHEL 6–9", "Bash", "Ansible", "YUM/DNF", "performance tuning", "on-call"):
        assert expected in result.job_description
    assert "What you get in return" in result.job_description
    assert "Multisport" in result.job_description
    for noise in ("technology image",):
        assert noise not in result.job_description


@pytest.mark.asyncio
async def test_nofluff_polish_support_offer_with_nested_marketing_recommendation():
    html = Path("tests/fixtures/nofluff_onerail_support.html").read_text(encoding="utf-8")

    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"content-type": "text/html"}, text=html)

    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )
    result = await service.extract(
        "https://nofluffjobs.com/pl/job/technical-support-engineer-l2-onerail-poland-krakow-2"
    )

    assert result.extraction_method == "html"
    assert result.company == "OneRail Poland Sp. z o.o."
    assert result.role == "Technical Support Engineer (L2)"
    for expected in (
        "2–4 years of experience",
        "JavaScript",
        "REST APIs",
        "SQL",
        "B2+",
        "Identify recurring issues and trends",  # Last task, hidden in the initial page UI.
        "front-line technical partner",
        "Competitive Compensation: Attractive salary and benefits package.",
        "Take the next step in your career",
    ):
        assert expected in result.job_description
    for noise in ("Salesforce Marketing Cloud", "Similar offer", "Opis oferty", "Oryginalny tekst."):
        assert noise not in result.job_description


@pytest.mark.parametrize("phrase", ["benefits", "job details", "what you get in return", "offer valid until"])
def test_nofluff_noise_markers_inside_offer_sentences_do_not_truncate_source(phrase):
    from app.services.job_extractors.nofluff import NoFluffExtractor

    html = f"""<main><h1>Support Engineer</h1><section id="posting-description">
    <h2>Offer description</h2>
    <p>Investigate customer incidents using logs, API requests and SQL queries.</p>
    <p>Discuss {phrase} with our team during the interview.</p>
    <p>Maintain documentation and improve support tooling.</p>
    <h3>Benefits</h3><ul><li>Private medical coverage</li></ul></section></main>"""

    result = NoFluffExtractor().extract(html)

    assert f"Discuss {phrase} with our team during the interview." in result.job_description
    assert "Maintain documentation and improve support tooling." in result.job_description
    assert "Benefits" in result.job_description
    assert "Private medical coverage" in result.job_description


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
        "Apply",
        "Save",
        "Similar offers",
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
    for context in ("Why this one is worth a look", "Competitive daily B2B rate", "Apply today"):
        assert context in result.job_description


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


def test_eldorado_extract_job_id():
    from app.services.job_extractors.eldorado import extract_job_id

    assert extract_job_id("https://czyjesteldorado.pl/praca/459530-technical-support-specialist-autenti-sa?utm_source=chatgpt.com") == "459530"
    assert extract_job_id("https://czyjesteldorado.pl/praca/459530") == "459530"
    assert extract_job_id("https://czyjesteldorado.pl/oferta/12345") == "12345"
    assert extract_job_id("https://czyjesteldorado.pl/job/987654") == "987654"
    assert extract_job_id("https://czyjesteldorado.pl/?id=459530") == "459530"
    assert extract_job_id("#459530") == "459530"
    assert extract_job_id("https://czyjesteldorado.pl/") is None


def test_eldorado_html_and_text_extraction():
    from app.services.job_extractors.eldorado import EldoradoExtractor

    html = """
    <html><body>
    <main>
      <h1>Technical Support Specialist</h1>
      <h2>AUTENTI Sp. z o.o.</h2>
      <div class="badges">
        <span class="badge">REST API</span>
        <span class="badge">HTTP</span>
        <span class="badge">JSON</span>
      </div>
      <article id="job-description">
        Provide support for Autenti integration platform. Diagnose API requests and errors.
      </article>
    </main>
    </body></html>
    """
    candidate = EldoradoExtractor().extract(html)
    assert candidate.usable
    assert candidate.role == "Technical Support Specialist"
    assert candidate.company == "AUTENTI Sp. z o.o."
    assert "PORTAL TECHNOLOGY TAGS" in candidate.job_description
    assert "REST API" in candidate.job_description
    assert "Diagnose API requests" in candidate.job_description

    text = """Technical Support Specialist
AUTENTI Sp. z o.o.
REST API
HTTP
JSON"""
    candidate_text = EldoradoExtractor().extract_text(text)
    assert candidate_text.usable
    assert candidate_text.role == "Technical Support Specialist"
    assert candidate_text.company == "AUTENTI Sp. z o.o."
    assert "REST API" in candidate_text.job_description


def test_eldorado_full_pasted_offer_extraction():
    from app.services.job_extractors.eldorado import EldoradoExtractor

    full_pasted = """to jest opis AUTENTI Sp. z o.o.
AUTENTI Sp. z o.o.
New
Technical Support Specialist

Brak informacji o wynagrodzeniu
Mid
Zdalnie
·
Kraków
Inne
·
B2B
#459530
·
Dodano wczoraj
·
0
Źródło: justjoin.it

Zapisz

Udostępnij
Aplikuj teraz
Tech Stack / Keywords

REST API
HTTP
JSON
Firma i stanowisko

Autenti to europejska platforma usług zaufania, która łączy ludzi i firmy w przestrzeni cyfrowej, zapewniając szybkość, wygodę i bezpieczeństwo.
Wymagania

Doświadczenie we wsparciu technicznym aplikacji lub systemów IT, obejmujące samodzielną diagnozę i rozwiązywanie zgłoszeń.
Umiejętność analizowania logów i danych systemowych, odtwarzania błędów oraz ustalania przyczyn problemów.
Praktyczna znajomość podstaw REST API, HTTP i JSON oraz narzędzi do testowania zapytań, takich jak Postman.
Obowiązki

Rozwiązywać bardziej złożone zgłoszenia techniczne przekazywane przez pierwszą linię wsparcia.
Analizować logi, dane systemowe i przebieg procesów, aby ustalać przyczyny problemów.
Benefity

Współpraca na zasadzie kontraktu B2B.
Inne informacje

Informujemy, że administratorem danych jest AUTENTI sp. z o.o.
"""
    candidate = EldoradoExtractor().extract_text(full_pasted)
    assert candidate.usable
    assert candidate.role == "Technical Support Specialist"
    assert candidate.company == "AUTENTI Sp. z o.o."
    assert "PORTAL TECHNOLOGY TAGS" in candidate.job_description
    assert "REST API" in candidate.job_description
    assert "REQUIREMENTS" in candidate.job_description
    assert "Doświadczenie we wsparciu technicznym" in candidate.job_description
    assert "RESPONSIBILITIES" in candidate.job_description
    assert "Rozwiązywać bardziej złożone zgłoszenia" in candidate.job_description
    assert "EMPLOYMENT CONDITIONS" in candidate.job_description
    assert "Kraków" in candidate.job_description
    assert "Zdalnie" in candidate.job_description
    assert "B2B" in candidate.job_description
    assert "Benefity" not in candidate.job_description
    assert "administratorem danych jest" not in candidate.job_description


@pytest.mark.asyncio
async def test_eldorado_remote_mcp_extraction():
    import json


    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/_mcp":
            body = json.loads(request.content.decode("utf-8"))
            if body.get("method") == "initialize":
                return httpx.Response(
                    200,
                    headers={"mcp-session-id": "mock-mcp-session-777", "content-type": "application/json"},
                    json={
                        "jsonrpc": "2.0",
                        "id": body.get("id"),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "serverInfo": {"name": "czyjesteldorado", "version": "1.0.0"},
                        },
                    },
                )
            if body.get("method") == "tools/call" and body.get("params", {}).get("name") == "search_jobs":
                phrase = body.get("params", {}).get("arguments", {}).get("phrase")
                if phrase == "#459530":
                    return httpx.Response(
                        200,
                        headers={"content-type": "application/json"},
                        json={
                            "jsonrpc": "2.0",
                            "id": body.get("id"),
                            "result": {
                                "structuredContent": {
                                    "jobs": [
                                        {
                                            "title": "Technical Support Specialist",
                                            "keywords": ["REST API", "HTTP", "JSON"],
                                            "company": "AUTENTI Sp. z o.o.",
                                            "cities": ["Kraków"],
                                            "work_modes": ["remote"],
                                            "contract_types": ["b2b"],
                                            "workload_types": ["other"],
                                            "seniority": "mid",
                                            "salary_from": None,
                                            "salary_to": None,
                                            "url": "https://czyjesteldorado.pl/praca/459530-technical-support-specialist-autenti-sa?utm_source=mcp",
                                            "posted_at": "2026-10-15T13:18:36+00:00",
                                        }
                                    ],
                                    "shown_results": 1,
                                    "total_results": 1,
                                }
                            },
                        },
                    )
        return httpx.Response(404)

    settings = Settings(_env_file=None, job_fetch_playwright_enabled=False)
    service = JobExtractorService(settings)
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler)
    )

    url = "https://czyjesteldorado.pl/praca/459530-technical-support-specialist-autenti-sa?utm_source=chatgpt.com"
    result = await service.extract(url)

    assert result.extraction_method == "html"
    assert result.company == "AUTENTI Sp. z o.o."
    assert result.role == "Technical Support Specialist"
    assert result.source == url
    assert "PORTAL TECHNOLOGY TAGS" in result.job_description
    assert "REST API" in result.job_description
    assert "HTTP" in result.job_description
    assert "JSON" in result.job_description
    assert "EMPLOYMENT CONDITIONS" in result.job_description
    assert "Lokalizacja: Kraków" in result.job_description
    assert "Tryb pracy: remote" in result.job_description
    assert "Forma zatrudnienia: b2b" in result.job_description
    assert "Data publikacji: 2026-10-15" in result.job_description

