import pytest
from starlette.testclient import TestClient

from app.core.config import Settings
from app.main import app
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import WorkflowResponse
from app.services.ai_provider import (
    AIProviderError,
    GeminiAuthError,
    ProviderUnavailableError,
)
from app.services.gemini_provider import GeminiProvider
from app.services.mock_provider import MockAIProvider
from app.services.resilient_provider import ResilientAIProvider


def job() -> JobRequest:
    return JobRequest(
        company="Acme Corp",
        role="Cloud Engineer",
        job_url="https://jobs.example.test/cloud",
        job_description="Deploy cloud infrastructure with Docker, Linux, and Python.",
    )


def sample_workflow_response(provider_name: str, model_name: str) -> WorkflowResponse:
    from tests.test_gemini_provider import analysis_payload, resume_payload

    return WorkflowResponse(
        analysis=analysis_payload(),
        resume=resume_payload(),
        provider_used=provider_name,
        model_used=model_name,
    )


class FailingProvider(MockAIProvider):
    def __init__(self, name: str, exc: Exception):
        super().__init__()
        self.name = name
        self.model = f"{name}-model"
        self.exc = exc

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        raise self.exc


class SucceedingProvider(MockAIProvider):
    def __init__(self, name: str):
        super().__init__()
        self.name = name
        self.model = f"{name}-model"

    async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
        return sample_workflow_response(self.name, self.model)


@pytest.mark.asyncio
async def test_ollama_to_gemini_fallback_success(profile):
    ollama_mock = FailingProvider("ollama", ProviderUnavailableError("Ollama connection refused"))
    gemini_mock = SucceedingProvider("gemini")

    router = ResilientAIProvider(
        providers={"ollama": ollama_mock, "gemini": gemini_mock},
        default_primary="ollama",
        default_fallback="gemini",
    )

    resp = await router.tailor(job(), profile, requested_provider="auto")
    assert resp.provider_used == "gemini"
    assert resp.fallback_used is True
    assert "Ollama connection refused" in (resp.fallback_reason or "")


@pytest.mark.asyncio
async def test_gemini_to_ollama_fallback_success(profile):
    gemini_mock = FailingProvider("gemini", ProviderUnavailableError("Gemini 503 Unavailable"))
    ollama_mock = SucceedingProvider("ollama")

    router = ResilientAIProvider(
        providers={"ollama": ollama_mock, "gemini": gemini_mock},
        default_primary="gemini",
        default_fallback="ollama",
    )

    resp = await router.tailor(job(), profile, requested_provider="gemini")
    assert resp.provider_used == "ollama"
    assert resp.fallback_used is True
    assert "Gemini 503 Unavailable" in (resp.fallback_reason or "")


@pytest.mark.asyncio
async def test_dual_failure_aggregates_error_messages(profile):
    ollama_mock = FailingProvider("ollama", ProviderUnavailableError("Ollama timeout"))
    gemini_mock = FailingProvider("gemini", ProviderUnavailableError("Gemini quota 429"))

    router = ResilientAIProvider(
        providers={"ollama": ollama_mock, "gemini": gemini_mock},
        default_primary="ollama",
        default_fallback="gemini",
    )

    with pytest.raises(AIProviderError) as exc_info:
        await router.tailor(job(), profile, requested_provider="auto")

    err = str(exc_info.value)
    assert "Both AI providers failed" in err
    assert "Ollama timeout" in err
    assert "Gemini quota 429" in err


@pytest.mark.asyncio
async def test_explicit_gemini_auth_error_fails_immediately_without_fallback(profile):
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key="",  # unconfigured
        gemini_model="gemini-2.5-flash",
    )
    real_gemini = GeminiProvider(settings)
    ollama_mock = SucceedingProvider("ollama")

    router = ResilientAIProvider(
        providers={"gemini": real_gemini, "ollama": ollama_mock},
        default_primary="gemini",
        default_fallback="ollama",
    )

    # When user explicitly selects gemini, missing key must immediately raise GeminiAuthError
    with pytest.raises(GeminiAuthError, match="Gemini API key is not configured"):
        await router.tailor(job(), profile, requested_provider="gemini")


def test_analyze_endpoint_preserves_form_data_on_provider_error(monkeypatch):
    import app.routes.web as web_routes
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        async def failing_tailor(job, profile, requested_provider="auto"):
            raise AIProviderError("Both AI providers failed. Ollama: timeout; Gemini: 429 quota")

        monkeypatch.setattr(app.state.provider, "tailor", failing_tailor)

        client.get("/")
        csrf_token = client.cookies.get("csrf_token")

        res = client.post(
            "/analyze",
            data={
                "company": "Preserved Bank",
                "role": "Lead DevOps Architect",
                "job_description": "We need an engineer experienced with Terraform, Docker, and Kubernetes deployment pipelines.",
                "job_url": "https://example.com/job/123",
                "llm_provider": "auto",
                "csrf_token": csrf_token,
            },
        )

        assert res.status_code == 502
        html = res.text
        # Check that error is displayed
        assert "Both AI providers failed" in html
        # Check that submitted form values are preserved in the HTML
        assert 'value="Preserved Bank"' in html
        assert 'value="Lead DevOps Architect"' in html
        assert 'value="https://example.com/job/123"' in html
        assert "We need an engineer experienced with Terraform" in html


@pytest.mark.asyncio
async def test_resilient_provider_enforces_budget_timeout(profile):
    import asyncio

    class SlowProvider(MockAIProvider):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
            await asyncio.sleep(0.5)
            return sample_workflow_response(self.name, "slow-model")

    router = ResilientAIProvider(
        providers={"ollama": SlowProvider("ollama")},
        default_primary="ollama",
        default_fallback="none",
        operation_budget_seconds=0.05,
    )

    with pytest.raises(ProviderUnavailableError, match="timed out"):
        await router.tailor(job(), profile, requested_provider="ollama")


@pytest.mark.asyncio
async def test_resilient_provider_aborts_fallback_if_insufficient_budget(profile):
    import asyncio

    class SlowFailingProvider(MockAIProvider):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
            await asyncio.sleep(0.05)
            raise ProviderUnavailableError("Slow primary failure")

    class FallbackProvider(MockAIProvider):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        async def tailor(self, job: JobRequest, profile: CandidateProfile) -> WorkflowResponse:
            return sample_workflow_response(self.name, "fb-model")

    # Budget is 3.0s, which is below the 5.0s fallback threshold
    router = ResilientAIProvider(
        providers={"ollama": SlowFailingProvider("ollama"), "gemini": FallbackProvider("gemini")},
        default_primary="ollama",
        default_fallback="gemini",
        operation_budget_seconds=3.0,
    )

    with pytest.raises(AIProviderError, match="insufficient"):
        await router.tailor(job(), profile, requested_provider="auto")

