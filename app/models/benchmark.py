from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class BenchmarkRequest(BaseModel):
    """Analysis-only paired benchmark; submitting explicitly authorizes model use."""
    model_config = ConfigDict(extra='forbid')
    urls: list[HttpUrl] = Field(min_length=1, max_length=3)
    ollama_model: str | None = Field(default=None, max_length=120, pattern=r'^[A-Za-z0-9][A-Za-z0-9._:/-]*$')
    context: Literal[32768, 65536, 98304, 131072] = 65536
    max_model_calls: int = Field(default=24, ge=1, le=48)
    recovery_calls: int = Field(default=1, ge=0, le=4)
    case_timeout_seconds: int = Field(default=90, ge=30, le=120)
    confirm_costs: Literal[True]

    @field_validator('urls')
    @classmethod
    def distinct_public_urls(cls, values):
        if len({str(value) for value in values}) != len(values):
            raise ValueError('Duplicate offer URLs are not allowed')
        if any(value.username or value.password for value in values):
            raise ValueError('Credentials are not allowed in offer URLs')
        return values


class BenchmarkJobResponse(BaseModel):
    task_id: str = Field(pattern=r'^[a-f0-9]{32}$')
    status: Literal['queued', 'running', 'completed', 'failed', 'rejected']
    stage: str
    status_url: str
    view_url: str
    report: dict | None = Field(default=None, description='Versioned incremental report. Token counts are provider-reported; input-composition fields are characters/bytes, not tokens.')
    error: str | None = None
