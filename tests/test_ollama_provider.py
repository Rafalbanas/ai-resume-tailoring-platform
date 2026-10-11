import json

import httpx
import pytest

from app.core.config import Settings
from app.models.candidate import CandidateProfile
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
    payload = profile.model_dump(mode="json")
    payload["projects"] = [
        {
            "name": "Python ML thesis project",
            "description": "Compared machine-learning models in Python.",
            "technologies": ["Python"],
            "facts": ["Trained and compared machine-learning models."],
        }
    ]
    profile = CandidateProfile.model_validate(payload)
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
    assert all(request["options"]["num_predict"] == 8192 for request in requests)
    assert all(request["options"]["num_ctx"] == 32768 for request in requests)
    assert all(
        "MASTER PROFILE IS THE ONLY SOURCE OF FACTS" in request["messages"][0]["content"] for request in requests
    )
    resume_schema = requests[1]["format"]
    assert resume_schema["properties"]["summary_source_fact_ids"]["minItems"] == 1
    assert resume_schema["properties"]["core_skills"]["items"]["enum"] == ["Python", "n8n", "Linux"]
    assert resume_schema["$defs"]["ResumeBullet"]["properties"]["source_fact_ids"]["items"]["enum"]
    project_schema = resume_schema["$defs"]["ResumeProject"]["properties"]
    assert project_schema["name"]["enum"] == ["Python ML thesis project"]
    assert project_schema["technologies"]["items"]["enum"] == ["Python", "n8n", "Linux"]
    assert "Python ML thesis project" not in project_schema["technologies"]["items"]["enum"]


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
    assert result.resume.experience[0].company == "Example Ltd"
    assert result.resume.experience[0].title == "Support Engineer"
    assert any("Kubernetes" in warning for warning in result.warnings)
    assert any("replaced" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_ollama_passes_keep_alive_and_configurable_timeouts(profile):
    captured_body = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal captured_body
        captured_body = json.loads(request.content)
        return httpx.Response(200, json={"message": {"content": json.dumps(analysis_payload())}})

    custom_settings = Settings(
        ollama_connect_timeout_seconds=5.0,
        ollama_read_timeout_seconds=120.0,
        ollama_keep_alive="20m",
    )
    p = OllamaProvider(custom_settings, transport=httpx.MockTransport(handler))
    assert p.connect_timeout == 5.0
    assert p.read_timeout == 120.0
    assert p.keep_alive == "20m"

    await p.analyze_job(job(), profile)
    assert captured_body.get("keep_alive") == "20m"


@pytest.mark.asyncio
async def test_ollama_logs_telemetry_without_cv_content(profile, caplog):
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "message": {"content": json.dumps(analysis_payload())},
                "total_duration": 15_000_000_000,
                "load_duration": 3_000_000_000,
                "prompt_eval_count": 250,
                "prompt_eval_duration": 4_000_000_000,
                "eval_count": 120,
                "eval_duration": 8_000_000_000,
            },
        )

    with caplog.at_level("INFO"):
        await provider(httpx.MockTransport(handler)).analyze_job(job(), profile)

    # Check telemetry line exists
    log_messages = [rec.message for rec in caplog.records]
    telemetry_logs = [m for m in log_messages if "Ollama call completed" in m]
    assert len(telemetry_logs) == 1
    # Check that durations and tokens are reported
    assert "load=3000.0ms" in telemetry_logs[0]
    assert "prompt_eval=4000.0ms (250 tokens)" in telemetry_logs[0]
    assert "eval=8000.0ms (120 tokens)" in telemetry_logs[0]
    # Check that candidate PII and CV content are NOT logged
    assert profile.personal.name not in telemetry_logs[0]
    assert "Built reliable" not in telemetry_logs[0]

