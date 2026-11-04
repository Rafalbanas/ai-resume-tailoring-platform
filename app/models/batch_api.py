"""Public response contracts for the versioned batch API."""
from typing import Literal

from pydantic import BaseModel


class BatchItem(BaseModel):
    url: str
    status: Literal['queued', 'running', 'completed', 'draft_ready', 'manual_required', 'review_required', 'failed']
    task_id: str | None = None
    draft_id: str | None = None
    analysis_url: str | None = None
    redirect_url: str | None = None
    slug: str | None = None
    preview_url: str | None = None
    pdf_url: str | None = None
    docx_url: str | None = None
    provider_used: str | None = None
    model_used: str | None = None
    fallback_used: bool | None = None
    fallback_reason: str | None = None
    error: str | None = None


class BatchResult(BaseModel):
    items: list[BatchItem]
    history_url: str
    redirect_url: str


class BatchResponse(BaseModel):
    task_id: str
    status: Literal['queued', 'running', 'completed', 'failed', 'rejected']
    status_url: str
    view_url: str
    stage: str
    result: BatchResult | None
    error: str | None


class BatchOptionsResponse(BaseModel):
    providers: list[str]
    ollama_models: list[str]
    ollama_models_unavailable: bool
    gemini_model: str
    templates: list[str]
    max_urls: int
    max_file_bytes: int
    default_allow_fallback: bool
    automatic_fallback_enabled: bool
