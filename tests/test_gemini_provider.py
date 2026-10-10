import json

import httpx
import pytest

from app.core.config import Settings
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.ai_provider import (
    GeminiAuthError,
    GeminiQuotaError,
    ProviderResponseError,
    ProviderUnavailableError,
)
from app.services.gemini_provider import GeminiProvider, to_gemini_schema


def job() -> JobRequest:
    return JobRequest(
        company="Acme Corp",
        role="Python Engineer",
        job_url="https://jobs.example.test/python",
        job_description="Build and maintain reliable Python services with Linux, FastAPI, and Docker.",
    )


def analysis_payload() -> dict:
    return {
        "company": "Acme Corp",
        "role": "Python Engineer",
        "strong_matches": ["Python", "Linux"],
        "partial_matches": ["Docker"],
        "missing_requirements": ["Kubernetes"],
        "supported_keywords": ["Python", "Linux"],
        "unsupported_keywords": ["Kubernetes"],
        "recommendation": "APPLY",
        "match_level": "HIGH",
        "reasoning_summary": "Strong hands-on experience in Python and Linux supports the core requirements.",
    }


def resume_payload() -> dict:
    return {
        "headline": "Python Engineer",
        "professional_summary": "Experienced Python engineer with focus on reliability and backend architecture.",
        "summary_source_fact_ids": ["summary:0"],
        "core_skills": ["Python", "Linux"],
        "selected_skill_ids": ["skill_python", "skill_linux"],
        "experience": [
            {
                "company": "Example Ltd",
                "title": "Support Engineer",
                "dates": "2022 – Present",
                "bullets": [
                    {
                        "text": "Maintained critical backend infrastructure.",
                        "source_fact_ids": ["experience:0:fact:0"],
                    }
                ],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
    }


def gemini_response_envelope(data: dict) -> dict:
    return {
        "candidates": [
            {
                "content": {
                    "parts": [{"text": json.dumps(data)}],
                    "role": "model",
                },
                "finishReason": "STOP",
            }
        ]
    }


def gemini_provider(
    transport: httpx.AsyncBaseTransport,
    api_key: str = "test-gemini-key",
    model: str = "gemini-3.1-flash-lite",
    max_retries: int = 1,
) -> GeminiProvider:
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key=api_key,
        gemini_model=model,
        gemini_base_url="https://generativelanguage.googleapis.com",
        gemini_timeout_seconds=30.0,
        gemini_max_retries=max_retries,
    )
    return GeminiProvider(settings, transport=transport)


def test_to_gemini_schema_flattens_and_cleans():
    schema = to_gemini_schema(TailoredResume.model_json_schema())
    serialized = json.dumps(schema)
    assert "$defs" not in schema
    assert "$ref" not in serialized
    assert "properties" in schema
    assert "experience" in schema["properties"]
    assert "type" in schema["properties"]["experience"]


@pytest.mark.asyncio
async def test_gemini_returns_valid_analysis_and_tailored_resume(profile):
    payload = profile.model_dump(mode="json")
    profile_model = CandidateProfile.model_validate(payload)
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        data = analysis_payload() if len(requests) == 1 else resume_payload()
        return httpx.Response(200, json=gemini_response_envelope(data))

    provider = gemini_provider(httpx.MockTransport(handler))
    result = await provider.tailor(job(), profile_model)

    assert result.provider_used == "gemini"
    assert result.model_used == "gemini-3.1-flash-lite"
    assert result.analysis.strong_matches == ["Python", "Linux"]
    assert result.resume.core_skills == ["Python", "Linux"]
    assert len(requests) == 2

    # Check auth header security: API key is in header, not URL
    for req in requests:
        assert req.headers.get("x-goog-api-key") == "test-gemini-key"
        assert "key=" not in str(req.url)
        body = json.loads(req.content)
        assert "generationConfig" in body
        assert body["generationConfig"]["responseMimeType"] == "application/json"
        assert "$defs" not in body["generationConfig"]["responseSchema"]
        assert body["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "minimal"}


@pytest.mark.asyncio
async def test_gemini_missing_api_key_raises_auth_error(profile):
    provider = gemini_provider(httpx.MockTransport(lambda req: httpx.Response(200)), api_key="")
    with pytest.raises(GeminiAuthError, match="Gemini API key is not configured"):
        await provider.tailor(job(), profile)


@pytest.mark.asyncio
async def test_gemini_401_403_raises_auth_error_without_retry(profile):
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        call_count += 1
        return httpx.Response(401, json={"error": {"code": 401, "message": "API key not valid"}})

    provider = gemini_provider(httpx.MockTransport(handler), max_retries=2)
    with pytest.raises(GeminiAuthError, match="invalid or lacks permission"):
        await provider.tailor(job(), profile)

    # Must fail immediately without wasteful retries on auth failure
    assert call_count == 1


@pytest.mark.asyncio
async def test_gemini_429_quota_exceeded_raises_quota_error(profile):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            headers={"Retry-After": "60"},
            json={"error": {"code": 429, "message": "Resource exhausted"}},
        )

    provider = gemini_provider(httpx.MockTransport(handler))
    with pytest.raises(GeminiQuotaError, match="rate limit or quota exceeded"):
        await provider.tailor(job(), profile)


@pytest.mark.asyncio
async def test_gemini_503_transient_retry_and_exhaustion(profile):
    attempts = 0

    async def fail_handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(503, json={"error": {"code": 503, "message": "Service unavailable"}})

    provider = gemini_provider(httpx.MockTransport(fail_handler), max_retries=1)
    with pytest.raises(ProviderUnavailableError, match="temporarily unavailable"):
        await provider.tailor(job(), profile)

    assert attempts == 2  # 1 initial + 1 retry


@pytest.mark.asyncio
async def test_gemini_timeout_raises_provider_unavailable(profile):
    async def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("Socket timeout")

    provider = gemini_provider(httpx.MockTransport(timeout_handler), max_retries=0)
    with pytest.raises(ProviderUnavailableError, match="timed out"):
        await provider.tailor(job(), profile)


@pytest.mark.asyncio
async def test_gemini_invalid_json_raises_provider_response_error(profile):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=gemini_response_envelope({"not_matching": "schema"}))

    provider = gemini_provider(httpx.MockTransport(handler), max_retries=0)
    with pytest.raises(ProviderResponseError):
        await provider.tailor(job(), profile)


@pytest.mark.asyncio
async def test_gemini_health_check():
    # Unconfigured
    unconf_provider = gemini_provider(httpx.MockTransport(lambda r: httpx.Response(200)), api_key="")
    health = await unconf_provider.health()
    assert health["status"] == "unconfigured"

    # Healthy
    async def ok_handler(request: httpx.Request) -> httpx.Response:
        assert request.headers.get("x-goog-api-key") == "test-key"
        return httpx.Response(200, json={"name": "models/gemini-3.1-flash-lite"})

    conf_provider = gemini_provider(httpx.MockTransport(ok_handler), api_key="test-key")
    health = await conf_provider.health()
    assert health["status"] == "ok"
    assert health["model"] == "gemini-3.1-flash-lite"
