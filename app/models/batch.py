"""Bounded, canonical batch input shared by JSON and TXT submissions."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, StrictBool, field_validator


def parse_url_file(content: bytes) -> list[str]:
    """Decode a maximum 64 KiB UTF-8 URL list, optionally prefixed with a BOM."""
    if not content:
        raise ValueError('File is empty')
    if len(content) > 64 * 1024:
        raise ValueError('File is too large')
    try:
        urls = content.decode('utf-8-sig').split()
    except UnicodeDecodeError:
        raise ValueError('File is not valid UTF-8') from None
    if not urls:
        raise ValueError('No URLs found in file')
    return urls


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')

    urls: list[str] = Field(min_length=1, max_length=20)
    llm_provider: Literal['auto', 'ollama', 'gemini', 'mock', 'n8n'] = 'auto'
    ollama_model: str = Field(default='', max_length=200)
    ollama_context: Literal[32768, 65536, 98304, 131072] = 65536
    gemini_model: str = Field(default='', max_length=100, pattern=r'^[A-Za-z0-9._-]*$')
    template_name: Literal['modern_sidebar', 'ats_classic'] = 'ats_classic'
    tailoring_level: float = Field(default=0.0, ge=0.0, le=1.0, allow_inf_nan=False)
    export: bool = True
    allow_fallback: StrictBool = False

    @field_validator('urls', mode='after')
    @classmethod
    def validate_urls(cls, urls: list[str]) -> list[str]:
        # Field bounds apply BEFORE deduplication, so repeats cannot bypass admission.
        validated, seen = [], set()
        for raw in urls:
            value = raw.strip()
            if not value or len(value) > 2048:
                raise ValueError('URL must contain 1–2048 characters')
            parsed = HttpUrl(value)
            if parsed.username is not None or parsed.password is not None or parsed.fragment is not None:
                raise ValueError('URL credentials and fragments are not allowed')
            canonical = str(parsed)
            if canonical not in seen:
                validated.append(canonical)
                seen.add(canonical)
        return validated
