"""Bound total body reception time, including clients that keep sending tiny chunks."""
import asyncio

from fastapi import HTTPException

AUTH_BODY_SECONDS = 15
FORM_BODY_SECONDS = 30
UPLOAD_BODY_SECONDS = 60


def deadline_receive(receive, seconds):
    deadline = asyncio.get_running_loop().time() + seconds
    complete = False

    async def bounded_receive():
        nonlocal complete
        if complete:
            return await receive()
        remaining = deadline - asyncio.get_running_loop().time()
        if remaining <= 0:
            raise HTTPException(408, 'Request body reception timed out')
        try:
            async with asyncio.timeout(remaining):
                message = await receive()
        except TimeoutError as exc:
            raise HTTPException(408, 'Request body reception timed out') from exc
        if message['type'] == 'http.disconnect' or (message['type'] == 'http.request' and not message.get('more_body', False)):
            complete = True
        return message

    return bounded_receive
