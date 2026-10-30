import httpx
import pytest

from app.core.config import Settings
from app.services.job_extractors import JobExtractorService, canonical_job_url
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.security import PublicUrlGuard
from tests.test_job_extractors import public_resolver

URL = 'https://entrypoint-prod.nofluffjobs.com/pl/job/trainee-data-engineer-vertex-recruitments-remote'


def test_known_entrypoint_maps_to_canonical_host_without_losing_offer_parameters():
    assert canonical_job_url(URL + '?source=mail#requirements') == URL.replace('entrypoint-prod.', '') + '?source=mail#requirements'


@pytest.mark.parametrize('url', [
    'https://entrypoint-prod.nofluffjobs.com.evil.example/pl/job/example',
    'https://user:password@entrypoint-prod.nofluffjobs.com/pl/job/example',
    'https://entrypoint-prod.nofluffjobs.com@evil.example/pl/job/example',
    'https://other.nofluffjobs.com/pl/job/example',
])
def test_unrelated_or_credentialed_urls_are_left_to_the_existing_guard(url):
    assert canonical_job_url(url) == url


@pytest.mark.asyncio
async def test_entrypoint_import_fetches_the_canonical_offer():
    seen = []

    async def handler(request):
        seen.append(request.headers["host"])
        return httpx.Response(200, headers={'Content-Type':'text/html'}, text='''<script type="application/ld+json">{
            "@type":"JobPosting", "title":"Trainee Data Engineer",
            "hiringOrganization":{"name":"Synthetic Recruiter"},
            "description":"<p>Learn to build data pipelines using Python and SQL, work with cloud data platforms, and develop practical engineering skills with mentoring.</p>"}</script>''')

    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(timeout_seconds=5,max_bytes=500000,max_redirects=3,guard=PublicUrlGuard(resolver=public_resolver), transport=httpx.MockTransport(handler))
    result = await service.extract(URL)
    assert seen == ['nofluffjobs.com']
    assert result.role == 'Trainee Data Engineer'
    assert result.source == URL.replace('entrypoint-prod.', '')
