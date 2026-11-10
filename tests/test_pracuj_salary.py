"""Synthetic salary-widget regressions, without accessing a real job portal."""
import html

import httpx
import pytest

from app.core.config import Settings
from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.job_extractors import JobExtractorService
from app.services.job_extractors.fetcher import SafeHttpFetcher
from app.services.job_extractors.pracuj import PracujExtractor
from app.services.job_extractors.security import PublicUrlGuard
from app.services.offer_salary import extract_offer_salary
from app.services.storage import Storage
from tests.test_job_extractors import public_resolver

SALARIES = '''10 000–14 000 zł
brutto / mies. | umowa o pracę
14 000–18 000 zł
netto (+ VAT) / mies. | kontrakt B2B
100–120 EUR / h · umowa zlecenie'''
OFFER = f'''Container Infrastructure Administrator
Synthetic Company O firmie
{SALARIES}
pełny etat
O projekcie
Maintain container platforms for enterprise applications on Linux and Windows.
Twój zakres obowiązków
Administer Kubernetes and Docker clusters and investigate production incidents.
Nasze wymagania
Experience with Linux, Windows, Kubernetes and Docker.
To oferujemy
Private healthcare.
Podobne oferty
99 000 PLN B2B'''


def assert_variants(value):
    for expected in ('10 000–14 000 zł', 'brutto', 'umowa o pracę',
                     '14 000–18 000 zł', 'netto', 'VAT', 'kontrakt B2B',
                     '100–120 EUR', 'umowa zlecenie'):
        assert expected in value
    assert '99 000' not in value


def test_pasted_pracuj_keeps_every_salary_variant():
    candidate = PracujExtractor().extract_text(OFFER)
    assert candidate.usable
    assert_variants(extract_offer_salary(candidate.job_description))
    assert 'Private healthcare' not in candidate.job_description


def test_english_salary_widget_layout():
    # Same public widget layout as the reported offer, with synthetic employer
    # and requirements. NBSP group separators must survive whitespace cleanup.
    salaries = ('11\u00a0000 – 13\u00a0000 zł\n'
                'gross / mth. | contract of employment\n'
                '14\u00a0700 – 18\u00a0900 zł\n'
                'net (+ VAT) / mth. | B2B contract')
    text = OFFER.replace(SALARIES, salaries)
    candidate = PracujExtractor().extract_text(text)
    value = extract_offer_salary(candidate.job_description)
    for expected in ('11 000 – 13 000 zł', 'gross / mth.', 'contract of employment',
                     '14 700 – 18 900 zł', 'net (+ VAT) / mth.', 'B2B contract'):
        assert expected in value


@pytest.mark.asyncio
async def test_url_salary_variants_survive_draft_application_and_history(tmp_path, resume_payload):
    blocks = []
    for line in OFFER.splitlines():
        tag = 'h2' if line in ('O projekcie', 'Twój zakres obowiązków', 'Nasze wymagania', 'To oferujemy') else 'p'
        blocks.append(f'<{tag}>{html.escape(line)}</{tag}>')
    markup = '<main><h1>Container Infrastructure Administrator</h1>' + ''.join(blocks) + '</main>'
    service = JobExtractorService(Settings(_env_file=None, job_fetch_playwright_enabled=False))
    service.fetcher = SafeHttpFetcher(
        1, 100_000, 2, guard=PublicUrlGuard(public_resolver),
        transport=httpx.MockTransport(lambda request: httpx.Response(
            200, headers={'content-type': 'text/html'}, text=markup)),
    )
    result = await service.extract('https://www.pracuj.pl/praca/synthetic,oferta,100123')
    assert result.extraction_method == 'html'
    assert_variants(result.salary_range)
    job = JobRequest(company=result.company, role=result.role,
                     job_description=result.job_description, salary_range=result.salary_range)
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation='APPLY', match_level='HIGH')
    resume = TailoredResume.model_validate(resume_payload)
    storage = Storage(tmp_path)
    draft = storage.save_draft(job, WorkflowResponse(analysis=analysis, resume=resume, warnings=[]))
    assert_variants(storage.load_draft(draft)[0].salary_range)
    assert_variants(storage.analysis_history()[0]['salary_range'])
    slug, _ = storage.save_application(job, analysis, resume, [], draft_id=draft)
    assert_variants(storage.load_application(slug)[0].salary_range)
    assert_variants(storage.history()[0]['salary_range'])
