"""Limit real model calls and their responses independently of model compliance."""
import asyncio
from contextlib import asynccontextmanager

import httpx

from app.services.ai_provider import ProviderResponseError


@asynccontextmanager
async def model_call(provider):
    budget = getattr(provider, 'resource_budget', None)
    if budget is None:
        yield
    else:
        async with budget.ai_call():
            yield


async def bounded_post(client, url, **kwargs):
    return await bounded_request(client, 'POST', url, **kwargs)


async def bounded_get(client, url, **kwargs):
    return await bounded_request(client, 'GET', url, **kwargs)


async def bounded_request(client, method, url, **kwargs):
    # HTTPX's read timeout resets for every chunk. Bound the entire exchange too.
    try:
        async with asyncio.timeout(client.timeout.read or 300):
            return await _bounded_request(client, method, url, **kwargs)
    except TimeoutError as exc:
        raise httpx.ReadTimeout('AI response exceeded its total deadline') from exc


async def _bounded_request(client, method, url, **kwargs):
    headers = dict(kwargs.pop('headers', {}) or {})
    headers['Accept-Encoding'] = 'identity'
    async with client.stream(method, url, headers=headers, **kwargs) as response:
        if response.headers.get('content-encoding', 'identity').lower() not in {'', 'identity'}:
            raise ProviderResponseError('Compressed AI responses are not accepted.')
        chunks, size = [], 0
        async def chunks_iter():
            if response.is_stream_consumed:
                yield response.content
            else:
                async for part in response.aiter_raw():
                    yield part
        async for chunk in chunks_iter():
            size += len(chunk)
            if size > 2 * 1024 * 1024:
                raise ProviderResponseError('AI response exceeds the size limit.')
            chunks.append(chunk)
        return httpx.Response(response.status_code, headers=response.headers, content=b''.join(chunks), request=response.request)
