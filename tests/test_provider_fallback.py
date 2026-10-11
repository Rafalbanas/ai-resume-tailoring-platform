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
async def test_explicit_gemini_auth_error_fails_when_fallback_disabled(profile):
    settings = Settings(
        _env_file=None,
        ai_provider="gemini",
        gemini_api_key="",  # unconfigured
        gemini_model="gemini-3.1-flash-lite",
    )
    real_gemini = GeminiProvider(settings)
    ollama_mock = SucceedingProvider("ollama")

    router = ResilientAIProvider(
        providers={"gemini": real_gemini, "ollama": ollama_mock},
        default_primary="gemini",
        default_fallback="ollama",
    )

    router.fallback_enabled = False
    # With fallback disabled, missing credentials fail without contacting Ollama.
    with pytest.raises(GeminiAuthError, match="Gemini API key is not configured"):
        await router.tailor(job(), profile, requested_provider="gemini")


def test_analyze_endpoint_preserves_form_data_on_provider_error(monkeypatch):
    import app.routes.web as web_routes
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        client.get("/login")
        client.post("/login", data={"username": "audit-tests", "password": "isolated-test-password",
                                  "csrf_token": client.cookies.get("csrf_token")})
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

        assert res.status_code == 202
        task_id = res.headers.get("X-Task-ID")
        assert task_id is not None

        # Verify task status and preserved payload
        task_res = client.get(f"/tasks/{task_id}")
        assert task_res.status_code == 200
        task_data = task_res.json()
        assert task_data["status"] == "failed"
        assert "Both AI providers failed" in task_data["error"]
        assert task_data["payload"]["job"]["company"] == "Preserved Bank"
        assert task_data["payload"]["job"]["role"] == "Lead DevOps Architect"
        assert "We need an engineer experienced with Terraform" in task_data["payload"]["job"]["job_description"]


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


@pytest.mark.asyncio
async def test_primary_timeout_triggers_fallback_with_stage_updates(profile):
    stages_reported = []

    def record_stage(stage: str):
        stages_reported.append(stage)

    class TimeoutProvider(MockAIProvider):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        async def tailor(self, job: JobRequest, profile: CandidateProfile, on_stage=None) -> WorkflowResponse:
            if on_stage:
                on_stage(f"Analizowanie ({self.name})...")
            raise ProviderUnavailableError(f"{self.name} timed out while generating the response.")

    class QuickFallbackProvider(MockAIProvider):
        def __init__(self, name: str):
            super().__init__()
            self.name = name

        async def tailor(self, job: JobRequest, profile: CandidateProfile, on_stage=None) -> WorkflowResponse:
            if on_stage:
                on_stage(f"Generowanie ({self.name})...")
            return sample_workflow_response(self.name, "quick-model")

    router = ResilientAIProvider(
        providers={"ollama": TimeoutProvider("ollama"), "gemini": QuickFallbackProvider("gemini")},
        default_primary="ollama",
        default_fallback="gemini",
        operation_budget_seconds=30.0,
    )

    resp = await router.tailor(job(), profile, requested_provider="auto", on_stage=record_stage)
    assert resp.provider_used == "gemini"
    assert resp.fallback_used is True
    assert "timed out" in resp.fallback_reason
    assert any("Przełączanie na provider rezerwowy (gemini)" in s for s in stages_reported)
    assert any("Generowanie (gemini)" in s for s in stages_reported)


def test_retry_task_idempotency_and_form_prefill(tmp_path, monkeypatch):
    import app.routes.web as web_routes
    from app.services.task_manager import TaskManager, TaskKind, TaskStatus

    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        client.get("/login")
        client.post("/login", data={"username": "audit-tests", "password": "isolated-test-password",
                                    "csrf_token": client.cookies.get("csrf_token")})
        client.headers["X-CSRF-Token"] = client.cookies.get("csrf_token")
        tm: TaskManager = app.state.task_manager

        # 1. Create a failed task
        payload = {
            "job": {
                "company": "Motorola Solutions Test",
                "role": "Technical Support Specialist",
                "job_url": "https://example.com/job/123",
                "job_description": "Support mission critical communication networks with Linux, SIP, and TCP/IP.",
            },
            "llm_provider": "ollama",
        }
        task = tm.create_task(TaskKind.TAILOR, payload, idempotency_key="test-key-12345")
        task.status = TaskStatus.FAILED
        task.error = "Both AI providers failed. ollama: timed out; gemini: timed out"
        tm._save_task(task)

        # 2. Test form prefill from failed task ID
        res = client.get(f"/?from_task={task.task_id}")
        assert res.status_code == 200
        html = res.text
        assert 'value="Motorola Solutions Test"' in html
        assert 'value="Technical Support Specialist"' in html
        assert 'Support mission critical communication networks' in html
        assert 'https://example.com/job/123' in html

        # 3. Test retry endpoint
        retry_res = client.post(f"/tasks/{task.task_id}/retry", headers={"Accept": "application/json"})
        assert retry_res.status_code == 202
        retry_data = retry_res.json()
        new_task_id = retry_data["task_id"]
        assert new_task_id != task.task_id

        # 4. Verify new task inherited payload
        new_task = tm.get_task(new_task_id)
        assert new_task is not None
        assert new_task.payload["job"]["company"] == "Motorola Solutions Test"

        # 5. Rapid second click while new task is active returns same view without creating a 3rd task
        dup_res = client.post(f"/tasks/{new_task_id}/retry", follow_redirects=False)
        assert dup_res.status_code == 303
        assert f"/tasks/{new_task_id}/view" in dup_res.headers["location"]


