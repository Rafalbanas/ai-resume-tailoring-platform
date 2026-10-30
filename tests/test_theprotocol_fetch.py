"""Browser-gated offers must reach the parser or report the actual failure."""

import httpx
import pytest

from app.core.config import Settings
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.playwright_renderer import BrowserRenderError, RenderedPage
from app.services.job_extractors.security import PublicUrlGuard
from tests.test_job_extractors import public_resolver

URL = 'https://theprotocol.it/szczegoly/praca/support,oferta,synthetic?searchId=synthetic&sug=single'
UNSUPPORTED = '''<html><title>Praca w branży IT - theprotocol.it</title>
<p>Hack the Planet! Zaktualizuj przeglądarkę.</p>
<script id="__NEXT_DATA__" type="application/json">
{"page":"/unsupportedBrowser","props":{"pageProps":{"isSupportedBrowser":false}}}
</script></html>'''
OFFER = '''<main><h1>Technical Support Engineer</h1>
<h2>Firma <span>:</span> <a>Example Support</a></h2>
<p>umowa o pracę (pełny etat)</p><h2>Nasze wymagania</h2>
<ul><li>Two years of experience supporting complex technical applications.</li>
<li>Good understanding of REST APIs, SQL, and relational databases.</li></ul>
<h2>Twój zakres obowiązków</h2><ul><li>Investigate incidents and communicate with engineering teams.</li></ul>
<h2>O projekcie</h2><p>Support a cloud platform used by international customers.</p>
<h2>To oferujemy</h2><p>Private healthcare.</p></main>'''


def service_for(handler, *, browser=False):
    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=browser))
    service.fetcher = SafeHttpFetcher(1, 100_000, 3, guard=PublicUrlGuard(public_resolver),
                                     transport=httpx.MockTransport(handler))
    return service


async def test_theprotocol_browser_gate_yields_complete_offer_with_identified_client():
    requests = []
    def handler(request):
        requests.append(request)
        agent = request.headers['User-Agent']
        compatible = all(token in agent for token in ('Mozilla/5.0', 'Chrome/', 'Safari/'))
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=OFFER if compatible else UNSUPPORTED)

    result = await service_for(handler).extract(URL)
    assert result.extraction_method == 'html'
    assert result.failure_reason is None
    assert result.role == 'Technical Support Engineer'
    assert result.company == 'Example Support'
    for text in ('Two years of experience', 'REST APIs, SQL', 'Investigate incidents', 'international customers'):
        assert text in result.job_description
    assert 'Private healthcare' not in result.job_description
    assert len(requests) == 1  # No browser is needed for this server-rendered offer.
    request = requests[0]
    assert 'CVTailor/1.0' in request.headers['User-Agent']
    assert request.headers['Host'] == 'theprotocol.it'
    assert request.url.host == '93.184.216.34'
    assert request.url.params['searchId'] == 'synthetic'
    assert request.extensions['sni_hostname'] == 'theprotocol.it'


async def test_browser_compatibility_is_selected_for_each_redirect_host():
    seen = []
    destinations = ['https://unrelated.example/job', 'https://jobs.theprotocol.it/job',
                    'https://nottheprotocol.it/job']
    def handler(request):
        seen.append((request.headers['Host'], request.headers['User-Agent']))
        if len(seen) <= len(destinations):
            return httpx.Response(302, headers={'location': destinations[len(seen) - 1]})
        return httpx.Response(200, headers={'content-type': 'text/html'}, text=OFFER)

    service = service_for(handler)
    await service.fetcher.fetch(URL)
    assert [host for host, _ in seen] == ['theprotocol.it', 'unrelated.example', 'jobs.theprotocol.it', 'nottheprotocol.it']
    for host, agent in seen:
        assert 'CVTailor/1.0' in agent
        assert agent.startswith('Mozilla/') == (host in {'theprotocol.it', 'jobs.theprotocol.it'})


@pytest.mark.parametrize('browser', ['disabled', 'unsupported', 'empty', 'error', 'offer'])
async def test_unsupported_browser_page_reports_reason_or_recovers(monkeypatch, browser):
    service = service_for(lambda request: httpx.Response(200, headers={'content-type': 'text/html'}, text=UNSUPPORTED), browser=browser != 'disabled')
    async def render(url):
        if browser == 'disabled':
            pytest.fail('Browser fallback is disabled')
        if browser == 'error':
            raise BrowserRenderError('Browser unavailable')
        return RenderedPage(url, {'unsupported': UNSUPPORTED, 'empty': '<main></main>', 'offer': OFFER}[browser])
    monkeypatch.setattr(service.renderer, 'render', render)

    result = await service.extract(URL)
    if browser == 'offer':
        assert result.failure_reason is None
        assert result.extraction_method == 'playwright'
        assert 'REST APIs, SQL' in result.job_description
    else:
        assert result.extraction_method == 'manual_required'
        assert result.failure_reason == 'unsupported_browser'
        assert result.company == result.role == result.job_description == ''


async def test_empty_browser_page_does_not_clear_original_http_block(monkeypatch):
    service = service_for(lambda request: httpx.Response(403), browser=True)
    async def render(url):
        return RenderedPage(url, '<main></main>')
    monkeypatch.setattr(service.renderer, 'render', render)
    result = await service.extract(URL)
    assert result.failure_reason == 'blocked'
    assert result.extraction_method == 'manual_required'
