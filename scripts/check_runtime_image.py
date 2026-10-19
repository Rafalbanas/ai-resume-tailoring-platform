#!/usr/bin/env python3
"""Run inside a built role image; all artifacts and identities are synthetic."""
import argparse
import asyncio
import importlib.metadata
import importlib.util
import json
import re
import shutil
import tempfile
from pathlib import Path

from scripts.runtime_requirements import requirements


def fixtures():
    from app.models.candidate import CandidateProfile
    from app.models.job import JobRequest
    from app.models.resume import TailoredResume
    from app.services.fact_validator import FactValidator
    profile = CandidateProfile.model_validate({
        'personal': {'name': 'Alex Example', 'email': 'alex@example.com'},
        'summary_facts': ['Provides technical support and automates operational tasks with Python.'],
        'skills': {'tools': ['Python']},
        'experience': [{'company': 'Example', 'title': 'Support Engineer', 'start': '2024', 'end': 'Present',
                        'facts': ['Automates operational tasks with Python.']}],
    })
    job = JobRequest(company='Example', role='Support Engineer', job_description='Python technical support and operational automation.')
    draft = TailoredResume(headline='Support Engineer', professional_summary=profile.summary_facts[0],
                           summary_source_fact_ids=['summary:0'], core_skills=['Python'], experience=[])
    return profile, FactValidator(profile).validate(draft, job).resume


def document_roundtrip():
    from app.services.docx_generator import generate_docx
    from app.services.pdf_generator import PDFGenerator
    from app.services.reference_cvs import ReferenceCVLibrary
    profile, resume = fixtures()
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        generator = PDFGenerator(Path('templates'), Path('static'), root)
        generator.generate(resume, profile, root/'resume.pdf', template_name='ats_classic', photo_enabled=False)
        generate_docx(resume, profile, root/'resume.docx', template_name='ats_classic', photo_enabled=False)
        assert (root/'resume.pdf').read_bytes().startswith(b'%PDF-')
        assert (root/'resume.docx').read_bytes().startswith(b'PK')
        for suffix in ['pdf', 'docx']:
            assert 'Alex Example' in ReferenceCVLibrary._extract_text(root/f'resume.{suffix}')
        preview = generator.render_preview(resume, profile, template_name='ats_classic', photo_enabled=False)
        assert 'preview-page' in preview and 'data:image/png;base64,' in preview
    print('Source-validated PDF/DOCX, reference extraction and raster preview passed')


async def browser_roundtrip():
    from playwright.async_api import async_playwright

    from app.services.job_extractors.playwright_renderer import _browser_launcher
    from app.services.processing import clean_environment
    async with async_playwright() as playwright:
        async with _browser_launcher(playwright.chromium.executable_path) as executable:
            browser = await playwright.chromium.launch(headless=True, executable_path=str(executable),
                env={**clean_environment(), 'HOME': str(executable.parent), 'TMPDIR': str(executable.parent)},
                args=['--disable-dev-shm-usage', '--no-sandbox'])
            page = await browser.new_page()
            await page.set_content('<title>Synthetic image check</title><p>Support Engineer</p>')
            assert await page.title() == 'Synthetic image check'
            await browser.close()
    print('Chromium passed using the application sandbox launcher')



async def browser_security_roundtrip():
    from unittest.mock import patch

    from app.services.job_extractors.fetcher import FetchedPage
    from app.services.job_extractors.playwright_renderer import SafePlaywrightRenderer
    from app.services.job_extractors.security import PublicUrlGuard

    hits = []
    async def internal_service(reader, writer):
        hits.append(await reader.read(4096))
        writer.close()
        await writer.wait_closed()
    async def resolver(host, port):
        return ['93.184.216.34']
    server = await asyncio.start_server(internal_service, '127.0.0.1', 0)
    async with server:
        target = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/synthetic-private'
        scripts = [f"fetch('{target}').catch(()=>{{}})", f"window.open('{target}')",
                   "const p=window.open('about:blank');const f=p.document.createElement('form');"
                   f"f.method='POST';f.action='{target}';p.document.body.appendChild(f);f.submit();"]
        for script in scripts:
            guarded = []
            async def fetch(fetcher, url, _guarded=guarded, _script=script, **kwargs):
                _guarded.append(url)
                await fetcher.guard.validate(url)
                return FetchedPage(url, '<html><body><script>' + _script + '</script><p>Offer</p></body></html>')
            with patch('app.services.job_extractors.playwright_renderer.SafeHttpFetcher.fetch', fetch):
                renderer = SafePlaywrightRenderer(PublicUrlGuard(resolver), 30, 100000, 3)
                page = await renderer.render('https://synthetic-offer.example.test/job')
                assert 'Offer' in page.html and target in guarded
                assert not hits
    print('Browser role blocked private requests from main pages, popups and blank-popup forms')


def api_startup():
    from fastapi.testclient import TestClient

    from app.core.config import Settings
    from app.main import create_app
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        shutil.copyfile('data/master_profile.example.json', root/'master_profile.json')
        shutil.copyfile('data/skills.example.json', root/'skills.json')
        settings = Settings(_env_file=None, data_dir=root, profile_mode='sample', ai_provider='mock',
            app_username='image-smoke', app_password='synthetic-image-password', csrf_secret='synthetic-image-secret-' * 3)
        with TestClient(create_app(settings)) as client:
            assert client.get('/health').status_code == 200
            assert client.get('/login').status_code == 200
    print('API startup, worker sandbox handshake, health and login passed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('role', choices=['api', 'documents', 'browser'])
    parser.add_argument('--rpc', action='store_true', help='API integration test against configured workers')
    args = parser.parse_args()
    assert not Path('/app/.env').exists()
    assert not Path('/app/.git').exists()
    assert not list(Path('/app').rglob('__pycache__'))
    assert {p.name for p in Path('/app/data').iterdir()} <= {'master_profile.example.json', 'skills.example.json'}
    for line in requirements(args.role):
        match = re.fullmatch(r'([\w-]+)(?:\[[\w, -]+\])?==([^\s]+)', line)
        assert importlib.metadata.version(match[1]) == match[2], match[1]
    unwanted = {'api': ['playwright', 'weasyprint', 'pypdfium2', 'pypdf', 'docx', 'PIL', 'pillow_heif'],
                'documents': ['playwright'],
                'browser': ['weasyprint', 'pypdfium2', 'pypdf', 'docx', 'PIL', 'pillow_heif']}[args.role]
    for module in unwanted:
        assert importlib.util.find_spec(module) is None, f'{module} should not be in the {args.role} image'
    if args.role == 'api':
        from app.main import app
        assert app is not None
        if args.rpc:
            api_startup()
            document_roundtrip()
            # Dedicated browser authentication/role check without relying on external URLs.
            from app.services.processing import ProcessingError, process
            try:
                process('browser', {'url': 'http://127.0.0.1/private', 'timeout': 2,
                                   'max_bytes': 10000, 'max_redirects': 1}, timeout=5)
            except ProcessingError as exc:
                assert 'Document is invalid' in str(exc), str(exc)
            else:
                raise AssertionError('Private URL was accepted by the browser worker')
            print('Dedicated browser RPC rejected a private URL; no local fallback')
    elif args.role == 'documents':
        from app.services.processing import process
        assert process('check', {}, timeout=10) == {'protocol': 1, 'network_blocked': True}
        document_roundtrip()
    else:
        asyncio.run(browser_roundtrip())
        asyncio.run(browser_security_roundtrip())
    print(json.dumps({'role': args.role, 'status': 'passed'}))


if __name__ == '__main__':
    main()
