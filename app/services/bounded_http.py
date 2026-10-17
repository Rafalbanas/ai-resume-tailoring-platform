"""Limit real model calls and their responses independently of model compliance."""
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
    headers = dict(kwargs.pop('headers', {}) or {})
    headers['Accept-Encoding'] = 'identity'
    async with client.stream('POST', url, headers=headers, **kwargs) as response:
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
