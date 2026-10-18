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
from app.services.job_extractors.pracuj import HEADINGS, PracujExtractor
from app.services.job_extractors.security import PublicUrlGuard
from app.services.job_sections import extract_sections
from tests.test_job_extractors import public_resolver
from tests.test_recording_demo import sign_in

FIXTURES=Path('tests/fixtures/pracuj')


def source(name):
    return (FIXTURES/f'{name}.txt').read_text()


def page(name):
    raw=source(name)
    candidate=PracujExtractor().extract_text(raw)
    blocks=[]
    for line in raw.splitlines():
        tag='h2' if line.casefold() in HEADINGS else 'p'
        blocks.append(f'<{tag}>{html.escape(line)}</{tag}>')
    short=json.dumps({'@type':'JobPosting','title':candidate.role,'hiringOrganization':{'name':candidate.company},'description':'Only a short preview of the offer. '+ 'Preview. '*10})
    return f'''<nav>Other jobs</nav><main><h1>{candidate.role}</h1>
    <span data-test="text-employerName">{candidate.company}</span>
    {''.join(blocks)}<h2>Other jobs</h2><p>Unrelated Terraform Architect</p></main>
    <script type="application/ld+json">{short}</script><footer>Cookie policy</footer>'''


@pytest.mark.parametrize('name,company,role', [('sii_support','Sii Sp. z o.o.','Specjalista/Specjalistka ds. wsparcia IT (f/m/x)'),('media_expert_support','Media Expert','IT Support Specialist (k/m)')])
def test_copied_pages_keep_employer_and_complete_sections(name,company,role):
    result=PracujExtractor().extract_text(source(name))
    assert result.company==company and result.role==role
    assert result.usable
    for heading in ['EMPLOYMENT CONDITIONS','OFFER DESCRIPTION','RESPONSIBILITIES','REQUIREMENTS','NICE TO HAVE']:
        assert heading in result.job_description
    for noise in ['Great Place to Work','Medicover','Domyślne CV','Synthetic_2026.pdf','Samochód','Cookie policy','ważna jeszcze','do 05 lis']:
        assert noise not in result.job_description


def test_sii_keeps_all_requirements_and_conflicting_location_preference():
    result=PracujExtractor().extract_text(source('sii_support'))
    for value in ['Network Infrastructure','System Administrator','Hardware','IT helpdesk','Microsoft Windows','Active Directory','Minimum 2 lata','Microsoft 365, Intune oraz Entra','min. B2','Prawo jazdy kat. B','Blieskastel i Heltersberg','języka niemieckiego']:
        assert value in result.job_description
    units,_=extract_sections(result.job_description)
    assert any('Minimum 2 lata' in u.quote and u.category=='mandatory' for u in units)
    assert any('Blieskastel' in u.quote and u.category=='preferred' for u in units)


def test_media_expert_basic_and_optional_qualifications_stay_separate():
    result=PracujExtractor().extract_text(source('media_expert_support'))
    assert 'nie wymagamy wcześniejszego doświadczenia komercyjnego' in result.job_description
    assert '8:00–16:00' in result.job_description
    assert 'Bracka 28a, Katowiceśląskie' in result.job_description
    units,_=extract_sections(result.job_description)
    assert any('Podstawowa znajomość Active Directory' in u.quote and u.category=='mandatory' for u in units)
    for value in ['Microsoft 365','Intune','PowerShell']:
        assert any(value in u.quote and u.category=='preferred' for u in units)
        assert not any(value in u.quote and u.category=='mandatory' for u in units)


@pytest.mark.parametrize('name',['sii_support','media_expert_support'])
def test_full_html_sections_override_short_jsonld(name):
    service=JobExtractorService(Settings(_env_file=None))
    result,method=service._extract_html('https://www.pracuj.pl/praca/support,oferta,100123',page(name))
    assert method=='html'
    assert 'RESPONSIBILITIES' in result.job_description and 'NICE TO HAVE' in result.job_description
    assert 'Unrelated Terraform Architect' not in result.job_description
    assert 'Only a short preview' not in result.job_description


@pytest.mark.asyncio
async def test_blocked_page_returns_manual_fallback_without_garbage():
    async def blocked(request):
        return httpx.Response(403,text='Access denied')
    service=JobExtractorService(Settings(_env_file=None,job_fetch_playwright_enabled=False))
    service.fetcher=SafeHttpFetcher(1,100000,2,guard=PublicUrlGuard(public_resolver),transport=httpx.MockTransport(blocked))
    result=await service.extract('https://www.pracuj.pl/praca/support,oferta,100123')
    assert result.extraction_method=='manual_required' and not result.job_description
    candidate,_=service._extract_html('https://www.pracuj.pl/praca/support,oferta,100123','<main><h1>Verify your browser</h1><p>'+ 'Access denied. '*30+'</p></main>')
    assert not candidate.usable


def test_clean_pasted_offer_api_and_csrf():
    with TestClient(app) as client:
        sign_in(client)
        payload={'text':source('media_expert_support'),'url':'https://www.pracuj.pl/praca/support,oferta,100123'}
        assert client.post('/api/clean-job-text',json=payload).status_code==403
        response=client.post('/api/clean-job-text',json=payload,headers={'X-CSRF-Token':client.cookies.get('csrf_token')})
        assert response.status_code==200
        result=response.json()
        assert result['company']=='Media Expert'
        assert result['role']=='IT Support Specialist (k/m)'
        assert 'Intune' in result['job_description'] and 'Medicover' not in result['job_description']


def test_inline_product_links_stay_in_one_requirement_and_company_label_is_removed():
    result=PracujExtractor().extract('''<main><h1>IT Support Specialist</h1><h2>Example Company <a>O firmie</a></h2>
      <h2>Nasze wymagania</h2><p>Podstawowa znajomość <a>Active Directory</a> / <a>Entra ID</a> oraz środowiska Windows.</p>
      <h2>Mile widziane</h2><p>Znajomość Intune.</p><h2>To oferujemy</h2><p>Private healthcare.</p></main>''')
    assert result.company=='Example Company'
    assert 'Podstawowa znajomość Active Directory / Entra ID oraz środowiska Windows.' in result.job_description
    assert 'Private healthcare' not in result.job_description


def test_metadata_and_saved_cv_widget_do_not_count_as_an_offer():
    result=PracujExtractor().extract_text('''IT Support Specialist
Example CompanyO firmie
praca stacjonarna, praca hybrydowa
umowa o pracę, kontrakt B2B
specjalista / specjalistka (mid / regular)
Domyślne CV Junior Support Specialist.pdf
''')
    assert not result.usable
    assert not result.job_description


@pytest.mark.asyncio
async def test_english_pracuj_offer_imports_full_description_without_browser():
    from bs4 import BeautifulSoup

    markup = (FIXTURES / 'alten_english.html').read_text()
    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver),
        transport=httpx.MockTransport(lambda request: httpx.Response(200, headers={'content-type': 'text/html'}, text=markup)),
    )
    result = await service.extract('https://pracuj.pl/praca/it-support-specialist-tychy,oferta,1005146191')
    assert result.extraction_method == 'html'
    assert result.failure_reason is None
    assert result.company == 'ALTEN Polska'
    assert result.role == 'IT Support Specialist'
    soup = BeautifulSoup(markup, 'html.parser')
    for heading in ('Your responsibilities', 'Our requirements'):
        section = soup.find('h2', string=heading).find_parent('section')
        items = section.find_all('li')
        assert len(items) >= 10
        for item in items:
            assert item.get_text(' ', strip=True) in result.job_description
    for noise in ('Medicover', 'Access to professional certifications', 'in house', 'agile'):
        assert noise not in result.job_description


def test_english_pasted_offer_separates_optional_requirements_and_benefits():
    result = PracujExtractor().extract_text('''Support Engineer
Example Ltd About the company
About the project
Support our enterprise Windows workplace and business applications.
Your responsibilities
Investigate incidents and maintain documentation for the support team.
Our requirements
Experience with Active Directory and Microsoft Intune.
Optional
PowerShell scripting experience.
What we offer
Private healthcare.
Benefits
Gym membership.
''')
    assert result.usable
    assert result.company == 'Example Ltd'
    assert result.role == 'Support Engineer'
    assert 'NICE TO HAVE\nPowerShell scripting experience.' in result.job_description
    assert 'Private healthcare' not in result.job_description
    assert 'Gym membership' not in result.job_description


@pytest.mark.asyncio
@pytest.mark.parametrize('failure,reason', [(403, 'blocked'), (429, 'blocked'), (503, 'fetch_failed'), ('timeout', 'timeout'), (200, 'description_unavailable')])
async def test_import_failure_reports_actual_reason(failure, reason):
    def handler(request):
        if failure == 'timeout':
            raise httpx.ReadTimeout('timed out', request=request)
        return httpx.Response(failure, headers={'content-type': 'text/html'}, text='<h1>Unavailable</h1>')

    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver), transport=httpx.MockTransport(handler),
    )
    result = await service.extract('https://pracuj.pl/praca/support,oferta,100123')
    assert result.extraction_method == 'manual_required'
    assert result.failure_reason == reason
    assert not result.job_description
