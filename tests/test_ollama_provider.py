import json

import httpx
import pytest

from app.core.config import Settings
from app.models.job import JobRequest
from app.services.ai_provider import AIProviderError
from app.services.fact_validator import FactValidator
from app.services.ollama_provider import OllamaProvider


def job() -> JobRequest:
    return JobRequest(
        company="Acme",
        role="Python Engineer",
        job_url="https://jobs.example.test/python",
        job_description="Build and support reliable Python services with Docker and Kubernetes in production.",
    )


def analysis_payload() -> dict:
    return {
        "company": "Acme",
        "role": "Python Engineer",
        "strong_matches": ["Python"],
        "partial_matches": ["Linux"],
        "missing_requirements": ["Kubernetes"],
        "supported_keywords": ["Python"],
        "unsupported_keywords": ["Kubernetes"],
        "recommendation": "REASONABLE_STRETCH",
        "match_level": "MEDIUM",
        "reasoning_summary": "The verified profile supports Python, while Kubernetes is not supported.",
    }


def resume_payload(*, unsupported: bool = False) -> dict:
    return {
        "headline": "Python Engineer",
        "professional_summary": "Builds reliable services.",
        "summary_source_fact_ids": ["summary:0"],
        "core_skills": ["Python", "Kubernetes"] if unsupported else ["Python"],
        "experience": [
            {
                "company": "Invented Corp" if unsupported else "Example Ltd",
                "title": "Platform Wizard" if unsupported else "Support Engineer",
                "dates": "2022 – Present",
                "bullets": [
                    {
                        "text": "Invented unsupported achievement.",
                        "source_fact_ids": ["experience:0:fact:0"],
                    }
                ],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
    }


def provider(transport: httpx.AsyncBaseTransport, reference_library=None) -> OllamaProvider:
    settings = Settings(
        _env_file=None,
        ai_provider="ollama",
        ollama_base_url="http://ollama.test:11434",
        ollama_model="qwen3.5:9b",
        ollama_timeout_seconds=30,
    )
    return OllamaProvider(settings, transport=transport, reference_library=reference_library)


class FakeReferenceLibrary:
    def select(self, role, description):
        return [
            {
                "target_role": "Reference Platform Engineer",
                "summary_example": "Reference-only wording.",
                "skills_example": ["Unsupported Reference Skill"],
                "experience_bullet_examples": ["Reference-only employer fact."],
                "section_order": ["summary", "experience"],
            }
        ]

    def layout_guide(self):
        return {"summary_max_chars": 400, "max_skills": 10, "max_bullets_per_role": 3}


@pytest.mark.asyncio
async def test_ollama_returns_valid_analysis_and_tailored_resume(profile):
    replies = [analysis_payload(), resume_payload()]
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        content = json.dumps(replies[len(requests) - 1])
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}, "done": True})

    result = await provider(httpx.MockTransport(handler)).tailor(job(), profile)

    assert result.analysis.strong_matches == ["Python"]
    assert result.resume.core_skills == ["Python"]
    assert [request["messages"][1]["content"] for request in requests]
    assert json.loads(requests[0]["messages"][1]["content"])["stage"] == "analyze_job"
    assert json.loads(requests[1]["messages"][1]["content"])["stage"] == "tailor_resume"
    assert all(request["format"]["type"] == "object" for request in requests)
    assert all(request["stream"] is False for request in requests)
    assert all("MASTER PROFILE IS THE ONLY SOURCE OF FACTS" in request["messages"][0]["content"] for request in requests)


@pytest.mark.asyncio
async def test_ollama_receives_reference_cvs_as_style_only(profile):
    requests = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(json.loads(request.content))
        payload = analysis_payload() if len(requests) == 1 else resume_payload()
        return httpx.Response(200, json={"message": {"content": json.dumps(payload)}})

    await provider(httpx.MockTransport(handler), FakeReferenceLibrary()).tailor(job(), profile)
    resume_request = json.loads(requests[1]["messages"][1]["content"])

    assert resume_request["reference_cvs_style_only"][0]["target_role"] == "Reference Platform Engineer"
    assert resume_request["layout_constraints"]["max_skills"] == 10
    assert "Never copy their people" in requests[1]["messages"][0]["content"]


@pytest.mark.asyncio
async def test_ollama_invalid_json_raises_readable_provider_error(profile):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"message": {"content": "not JSON"}})

    with pytest.raises(AIProviderError, match="invalid structured JSON"):
        await provider(httpx.MockTransport(handler)).analyze_job(job(), profile)


@pytest.mark.asyncio
async def test_ollama_timeout_raises_readable_provider_error(profile):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(AIProviderError, match="timed out"):
        await provider(httpx.MockTransport(handler)).analyze_job(job(), profile)


@pytest.mark.asyncio
async def test_ollama_connection_failure_raises_readable_provider_error(profile):
    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(AIProviderError, match="Cannot connect to Ollama"):
        await provider(httpx.MockTransport(handler)).analyze_job(job(), profile)


@pytest.mark.asyncio
async def test_ollama_health_checks_configured_model():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/tags"
        return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})

    result = await provider(httpx.MockTransport(handler)).health()
    assert result == {"status": "ok", "provider": "ollama", "model": "qwen3.5:9b"}


@pytest.mark.asyncio
async def test_truth_lock_still_removes_unsupported_ollama_facts(profile):
    replies = [analysis_payload(), resume_payload(unsupported=True)]
    call_count = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        content = json.dumps(replies[call_count])
        call_count += 1
        return httpx.Response(200, json={"message": {"content": content}})

    response = await provider(httpx.MockTransport(handler)).tailor(job(), profile)
    result = FactValidator(profile).validate(response.resume, job())

    assert "Kubernetes" not in result.resume.core_skills
    assert not result.resume.experience
    assert any("Kubernetes" in warning for warning in result.warnings)
    assert any("Invented Corp" in warning for warning in result.warnings)
