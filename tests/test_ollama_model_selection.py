import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel

from app.core.config import Settings
from app.services.ai_provider import AIProviderError
from app.services.ollama_provider import OllamaProvider
from app.services.resilient_provider import ResilientAIProvider


def provider_with_models(limit=131072):
    def handle(request):
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "ISTA/Qwen:IQ2_XS"}, {"name": "qwen3.5:9b"}]})
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"model_info": {"qwen.context_length": limit}})
        raise AssertionError(request.url)
    return OllamaProvider(Settings(_env_file=None, ollama_tokenizer_path=""), transport=httpx.MockTransport(handle))


@pytest.mark.asyncio
async def test_selection_is_isolated_and_shares_inference_limit():
    provider = provider_with_models()
    original = provider.model
    selected = await provider.for_model("ISTA/Qwen:IQ2_XS", 65536)
    assert selected.model == "ISTA/Qwen:IQ2_XS"
    assert selected.num_ctx == 65536
    assert provider.model == original
    assert provider.num_ctx == 32768
    assert selected.semaphore is provider.semaphore
    assert selected.call_metrics is not provider.call_metrics
    assert selected._run_metrics is not provider._run_metrics


@pytest.mark.asyncio
@pytest.mark.parametrize("model,context,limit", [
    ("not-installed", 65536, 131072),
    ("ISTA/Qwen:IQ2_XS", 65536, 32768),
    ("ISTA/Qwen:IQ2_XS", 999999, 131072),
])
async def test_unsupported_selection_is_rejected(model, context, limit):
    with pytest.raises(AIProviderError):
        await provider_with_models(limit).for_model(model, context)


@pytest.mark.asyncio
async def test_listing_preserves_exact_model_names():
    assert await provider_with_models().available_models() == ["ISTA/Qwen:IQ2_XS", "qwen3.5:9b"]


@pytest.mark.asyncio
@pytest.mark.parametrize("context", [32768, 65536, 98304, 131072])
async def test_selected_model_and_context_are_sent_to_ollama(context):
    selected = await provider_with_models().for_model("ISTA/Qwen:IQ2_XS", context)
    sent = []

    class Answer(BaseModel):
        text: str

    def handle(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json={"message": {"content": '{"text":"ok"}'}, "done_reason": "stop"})

    selected.transport = httpx.MockTransport(handle)
    result = await selected._chat(Answer, "Return an answer", {})
    assert result.text == "ok"
    assert sent[0]["model"] == "ISTA/Qwen:IQ2_XS"
    assert sent[0]["options"]["num_ctx"] == context


@pytest.mark.asyncio
async def test_discovery_failure_still_uses_configured_fallback(resume_payload):
    from app.models.job import JobAnalysis, JobRequest
    from app.models.resume import TailoredResume, WorkflowResponse

    job = JobRequest(company="Test", role="Engineer", job_description="A complete synthetic job description.")
    result = WorkflowResponse(
        analysis=JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                             missing_requirements=[], recommendation="RETRY", match_level="UNRELIABLE"),
        resume=TailoredResume.model_validate(resume_payload),
    )
    def unavailable(request):
        raise httpx.ConnectError("Offline", request=request)
    provider = provider_with_models()
    provider.transport = httpx.MockTransport(unavailable)
    selected = provider.with_selection(provider.model, 65536)

    class Answer(BaseModel):
        text: str

    async def attempt(*args, **kwargs):
        await selected._chat(Answer, "test", {})
        raise AssertionError("Unreachable")
    selected.tailor = attempt
    fallback = SimpleNamespace(name="gemini", model="test-fallback", api_key="test",
                               tailor=AsyncMock(return_value=result))
    router = ResilientAIProvider({"ollama": selected, "gemini": fallback})
    response = await router.tailor(job, None, requested_provider="ollama")
    assert response.fallback_used
    assert response.provider_used == "gemini"
    fallback.tailor.assert_awaited_once()
    assert provider.num_ctx == 32768
