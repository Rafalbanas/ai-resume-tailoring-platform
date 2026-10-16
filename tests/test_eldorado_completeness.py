import httpx
import pytest

from app.core.config import Settings
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.eldorado import EldoradoExtractor, candidate_from_job_data
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.pasted import clean_pasted_offer
from app.services.job_extractors.security import PublicUrlGuard
from tests.test_job_extractors import public_resolver

URL = "https://czyjesteldorado.pl/praca/447799-l2-technical-support-engineer-andersen-lab"
TEXT = """[Andersen Lab](https://czyjesteldorado.pl/praca/firma/andersen-lab)
# L2 Technical Support Engineer
12 000 - 15 000 PLN/ mies.B2B (netto)
svgMidsvgZdalnie·PolandsvgFull-time·B2B
#447799·Dodano 16 dni temu·svg14
Źródło: SOLID.Jobssvg
svgZapiszsvgUdostępnij
## Tech Stack / Keywords
Linux
REST
## Firma i stanowiskosvg
Andersen is a global software development company supporting businesses worldwide.
## Wymaganiasvg
- svgHands-on experience in L2 Technical Support troubleshooting production environments for 2+ years.
- svgPractical experience analyzing service logs and checking pod/service health in Docker and Kubernetes (kubectl).
- svgAvailability for off-hours on-call coverage (Mon–Fri 00:00–05:30 CET, Sat–Sun 24/7).
**Nice to have:**
- svgEnglish proficiency from Upper-Intermediate and above.
## Obowiązkisvg
- svgConduct browser diagnostics using Chrome DevTools and analyzing video segments, manifests, and buffering issues.
## Benefitysvg
- svgFlexible working hours.
"""


def test_actual_markdown_with_glued_icons_preserves_sections():
    candidate = clean_pasted_offer(TEXT, URL)
    assert candidate.role == "L2 Technical Support Engineer"
    assert candidate.company == "Andersen Lab"
    description = candidate.job_description
    assert "Docker and Kubernetes (kubectl)" in description
    assert "Mon–Fri 00:00–05:30 CET, Sat–Sun 24/7" in description
    assert "NICE TO HAVE\nEnglish proficiency" in description
    assert "RESPONSIBILITIES\nConduct browser diagnostics" in description
    for noise in ("svg", "Zapisz", "Flexible working hours", "Dodano"):
        assert noise not in description


@pytest.mark.asyncio
@pytest.mark.parametrize("blocked", [True, False])
async def test_metadata_does_not_prevent_attempt_to_fetch_full_page(monkeypatch, blocked):
    metadata = candidate_from_job_data({
        "title": "L2 Technical Support Engineer", "company": "Andersen Lab",
        "keywords": ["Linux", "REST"], "cities": ["Poland"], "seniority": "mid",
    })

    async def remote(*args, **kwargs):
        return metadata

    monkeypatch.setattr(EldoradoExtractor, "fetch_remote", remote)
    requests = []

    async def handler(request):
        requests.append(str(request.url))
        if blocked:
            return httpx.Response(403)
        return httpx.Response(200, headers={"content-type": "text/html"}, text="""<main><h1>L2 Technical Support Engineer</h1>
        <a href='/praca/firma/andersen-lab'>Andersen Lab</a>
        <h2>Wymagania</h2><p>Practical experience analyzing service logs and checking
        pod/service health in Docker and Kubernetes (kubectl).</p></main>""")

    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(1, 100_000, 2, guard=PublicUrlGuard(public_resolver),
                                    transport=httpx.MockTransport(handler))
    result = await service.extract(URL)
    assert len(requests) == 1
    assert httpx.URL(requests[0]).path == httpx.URL(URL).path
    if blocked:
        assert result.extraction_method == "manual_required"
        assert result.company == "Andersen Lab"
        assert "REQUIREMENTS" not in result.job_description
        assert "Cloudflare" not in result.job_description
    else:
        assert result.extraction_method == "html"
        assert result.company == "Andersen Lab"
        assert "Docker and Kubernetes" in result.job_description


def test_cloudflare_challenge_is_not_an_offer():
    service = JobExtractorService(Settings(_env_file=None))
    candidate, _ = service._extract_html(URL, "<main><h1>Just a moment...</h1><p>" + "Verify your browser. " * 30 + "</p></main>")
    assert not candidate.usable
