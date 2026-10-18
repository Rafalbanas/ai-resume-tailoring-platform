import html
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.pasted import clean_pasted_offer
from app.services.job_extractors.security import PublicUrlGuard
from app.services.job_extractors.theprotocol import TheProtocolExtractor
from app.services.job_sections import extract_sections
from tests.test_job_extractors import public_resolver
from tests.test_recording_demo import sign_in

URL = 'https://theprotocol.it/szczegoly/praca/inzynier-oprogramowania,oferta,01000000-302a-ae26-d429-08df1a0903f1'
TEXT = Path('tests/fixtures/theprotocol_vix_software_engineer.txt').read_text()


@pytest.mark.parametrize('url', ['', URL, URL + '?utm_source=chatgpt.com'])
def test_full_pasted_page_keeps_offer_content_and_metadata(url):
    result = clean_pasted_offer(TEXT, url)
    assert result.usable
    assert result.company == 'VIX Automation Sp. z o.o.'
    assert result.role == 'Inżynier Oprogramowania (m/k)'
    for value in (
        'umowa o pracę (pełny etat)', 'poziom: junior • mid',
        'tryb pracy: hybrydowa • stacjonarna', 'Katowice, śląskie',
        'sporadyczne, kilkudniowe wyjazdy głównie na terenie Polski',
    ):
        assert value in result.job_description
    # Every source line in the actual qualification/duty/project sections survives.
    source = TEXT.split('NASZE WYMAGANIA\n', 1)[1].split('Tak organizujemy naszą pracę', 1)[0]
    headings = {'MILE WIDZIANE', 'TWÓJ ZAKRES OBOWIĄZKÓW', 'O projekcie'}
    for line in source.splitlines():
        if line.strip() and line not in headings:
            assert line in result.job_description
    for noise in (
        'quick apply', 'start ASAP', 'Ekstra benefity', 'brak widełek',
        'Szczegóły wynagrodzenia', 'Premia z udziałem w zyskach', 'wewnątrz organizacji',
        'prywatna opieka medyczna', 'Jesteśmy dystrybutorem', 'podsumowanie oferty',
        'Zgłaszam się do', 'rozwiń formularz', 'Brakuje Ci informacji?', 'napisz wiadomość',
    ):
        assert noise not in result.job_description
    assert result.job_description.count('prawo jazdy kat. B') == 1


def test_technology_priorities_reach_requirement_analysis_without_promotion():
    result = clean_pasted_offer(TEXT)
    units, _ = extract_sections(result.job_description)
    assert any(u.quote == 'HMI/SCADA' and u.category == 'mandatory' for u in units)
    for technology in ('Visual Basic', 'SQL', 'C#'):
        assert any(technology in u.quote and u.category == 'preferred' for u in units)
        assert not any(technology in u.quote and u.category == 'mandatory' for u in units)
    assert any('prawo jazdy kat. B' in u.quote and u.category == 'mandatory' for u in units)
    assert any('systemów SCADA / PLC / MES' in u.quote and u.category == 'responsibility' for u in units)


def offer_html():
    # Keep the copied page's order, with nested markup and a short schema preview.
    blocks = []
    for line in TEXT.splitlines():
        if not line.strip():
            continue
        if line == 'Inżynier Oprogramowania (m/k)':
            tag = 'h1'
        elif line.startswith('Firma:') or line.casefold() in TheProtocolExtractor.headings:
            tag = 'h2'
        else:
            tag = 'p'
        blocks.append(f'<{tag}><span>{html.escape(line)}</span></{tag}>')
    schema = json.dumps({
        '@type': 'JobPosting', 'title': 'Inżynier Oprogramowania (m/k)',
        'hiringOrganization': {'name': 'VIX Automation Sp. z o.o.'},
        'description': 'Short preview. ' * 12,
    })
    return '<main>' + ''.join(blocks) + f'</main><script type="application/ld+json">{schema}</script>'


@pytest.mark.asyncio
async def test_url_import_prefers_full_sections_over_schema_preview():
    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver),
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={'content-type': 'text/html'}, text=offer_html(),
        )),
    )
    result = await service.extract(URL)
    assert result.extraction_method == 'html'
    assert result.company == 'VIX Automation Sp. z o.o.'
    assert result.role == 'Inżynier Oprogramowania (m/k)'
    assert result.job_description == clean_pasted_offer(TEXT).job_description
    assert 'Short preview' not in result.job_description


def test_cleaning_api_works_without_network_and_requires_csrf(monkeypatch):
    async def forbidden_fetch(*args, **kwargs):
        pytest.fail('Cleaning pasted text must not access the network')

    with TestClient(app) as client:
        sign_in(client)
        monkeypatch.setattr(SafeHttpFetcher, 'fetch', forbidden_fetch)
        payload = {'text': TEXT, 'url': URL}
        assert client.post('/api/clean-job-text', json=payload).status_code == 403
        response = client.post('/api/clean-job-text', json=payload,
                               headers={'X-CSRF-Token': client.cookies.get('csrf_token')})
        assert response.status_code == 200
        result = response.json()
        assert result['company'] == 'VIX Automation Sp. z o.o.'
        assert result['role'] == 'Inżynier Oprogramowania (m/k)'
        assert result['job_description'] == clean_pasted_offer(TEXT).job_description


@pytest.mark.parametrize('text', [
    'Hack the Planet! Zaktualizuj przeglądarkę. ' * 20,
    'quick apply\nFirma: Example Ltd\npodsumowanie oferty\naplikuj szybko',
    'TECHNOLOGIE WYMAGANE\nTECHNOLOGIE MILE WIDZIANE\npodsumowanie oferty',
])
def test_controls_or_browser_error_do_not_count_as_an_offer(text):
    assert not clean_pasted_offer(text, URL).usable
    assert not TheProtocolExtractor().extract(f'<main><p>{html.escape(text)}</p></main>').usable
