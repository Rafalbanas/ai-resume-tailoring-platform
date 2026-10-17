"""Untrusted offer scripts must never bypass the server's network policy."""
import asyncio

import pytest

from app.services.job_extractors.fetcher import FetchedPage
from app.services.job_extractors.playwright_renderer import SafePlaywrightRenderer
from app.services.job_extractors.security import PublicUrlGuard


@pytest.mark.parametrize('kind', ['main-page', 'popup', 'blank-popup'])
async def test_all_browser_pages_block_requests_to_private_services(monkeypatch, kind):
    hits, guarded = [], []

    async def internal_service(reader, writer):
        hits.append(await reader.readuntil(b'\r\n\r\n'))
        writer.write(b'HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n')
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    async def resolver(host, port):
        return ['93.184.216.34']

    server = await asyncio.start_server(internal_service, '127.0.0.1', 0)
    async with server:
        target = f'http://127.0.0.1:{server.sockets[0].getsockname()[1]}/synthetic-private-service'
        scripts = {
            'main-page': f"fetch('{target}').catch(()=>{{}})",
            'popup': f"window.open('{target}')",
            'blank-popup': ("const p=window.open('about:blank');const f=p.document.createElement('form');"
                            f"f.method='POST';f.action='{target}';p.document.body.appendChild(f);f.submit();"),
        }

        async def fake_public_fetch(self, url, **kwargs):
            guarded.append(url)
            await self.guard.validate(url)
            return FetchedPage(url, '<html><body><script>' + scripts[kind] + '</script><p>Offer</p></body></html>')

        monkeypatch.setattr('app.services.job_extractors.playwright_renderer.SafeHttpFetcher.fetch', fake_public_fetch)
        renderer = SafePlaywrightRenderer(PublicUrlGuard(resolver), 5, 100000, 3)
        page = await renderer.render('https://synthetic-offer.example.test/job')
        assert 'Offer' in page.html
        assert target in guarded  # The script ran and its request reached our policy.
        assert not hits  # No request reached the synthetic internal service.
