from starlette.testclient import TestClient

import app.routes.web as web_routes
from app.main import app
from app.models.resume import (
    ResumeBullet,
    ResumeExperience,
    ResumeProject,
    TailoredResume,
)
from app.services.diagnostics import DiagnosticLogStore
from app.services.storage import compute_pre_fit_diff


def make_resume(
    skills: list[str],
    summary: str,
    bullets: list[str],
    projects: list[str],
) -> TailoredResume:
    return TailoredResume(
        headline="Software Engineer",
        professional_summary=summary,
        summary_source_fact_ids=["summary:0"],
        core_skills=skills,
        selected_skill_ids=[f"skill_{s.lower()}" for s in skills],
        experience=[
            ResumeExperience(
                company="Tech Corp",
                title="Engineer",
                dates="2022 – Present",
                bullets=[ResumeBullet(text=b, source_fact_ids=["exp:0"]) for b in bullets],
            )
        ],
        projects=[
            ResumeProject(name=p, description="Desc", technologies=[], source_fact_ids=["proj:0"])
            for p in projects
        ],
        education=[],
        certifications=[],
    )


def test_compute_pre_fit_diff_detects_all_trimming():
    pre_fit = make_resume(
        skills=["Python", "FastAPI", "Docker", "PostgreSQL", "Redis"],
        summary="A comprehensive, detailed summary explaining five years of scalable Python architecture.",
        bullets=[
            "Built distributed microservice communicating over RabbitMQ with high throughput.",
            "Refactored legacy monolith into domain-driven microservices.",
            "Optimized query performance reducing latencies by 45 percent.",
        ],
        projects=["ALPR Project", "Candle Store", "Cycling Tracker"],
    )

    fitted = make_resume(
        skills=["Python", "FastAPI", "Docker"],
        summary="A comprehensive, detailed summary explaining five years of scalable Python architecture."[:55],
        bullets=[
            "Built distributed microservice communicating over RabbitMQ with high throughput."[:45],
            "Refactored legacy monolith into domain-driven microservices.",
        ],
        projects=["ALPR Project", "Candle Store"],
    )

    diff = compute_pre_fit_diff(pre_fit, fitted)

    assert "PostgreSQL" in diff["trimmed_skills"]
    assert "Redis" in diff["trimmed_skills"]
    assert "Cycling Tracker" in diff["trimmed_projects"]
    assert diff["summary_shortened"] is True
    # Bullets trimmed and shortened
    assert any(b["text"] == "Optimized query performance reducing latencies by 45 percent." for b in diff["trimmed_bullets"])
    assert any("RabbitMQ" in b["original"] for b in diff["shortened_bullets"])
    assert diff["total_items"] > 0


def test_diagnostic_log_store_fifo_rotation(tmp_path):
    store = DiagnosticLogStore(tmp_path, max_entries=5)

    for i in range(10):
        store.record(
            company=f"Company {i}",
            role=f"Role {i}",
            requested_provider="auto",
            provider_used="ollama",
            model_used="qwen3.5:9b",
            fallback_occurred=False,
            duration_ms=100 + i,
        )

    runs = store.list_runs()
    assert len(runs) == 5
    # The newest run is at index 0 (Company 9)
    assert runs[0]["company"] == "Company 9"
    # Oldest retained is Company 5
    assert runs[-1]["company"] == "Company 5"

    store.clear()
    assert len(store.list_runs()) == 0


def test_compare_and_diagnostics_web_routes(monkeypatch):
    from app.services.mock_provider import MockAIProvider
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *args, **kwargs: None)

    with TestClient(app) as client:
        client.auth = ("audit-tests", "isolated-test-password")
        # Mock providers to avoid waiting for external Ollama/Gemini connections
        mock_p1 = MockAIProvider(app.state.skills_bank)
        mock_p1.name = "ollama"
        mock_p1.model = "qwen3.5:9b"
        mock_p2 = MockAIProvider(app.state.skills_bank)
        mock_p2.name = "gemini"
        mock_p2.model = "gemini-3.1-flash-lite"
        monkeypatch.setattr(app.state, "providers", {"ollama": mock_p1, "gemini": mock_p2})

        # 1. GET /diagnostics
        diag_res = client.get("/diagnostics")
        assert diag_res.status_code == 200
        assert "System Diagnostics" in diag_res.text

        # 2. GET /compare
        compare_res = client.get("/compare")
        assert compare_res.status_code == 200
        assert "Compare Ollama vs Gemini side-by-side" in compare_res.text

        # 3. POST /compare
        compare_post_res = client.post(
            "/compare",
            data={
                "company": "Test Compare Co",
                "role": "Python Backend Developer",
                "job_description": "We are looking for a Python developer with Linux and Docker knowledge.",
                "csrf_token": "token",
            },
        )
        assert compare_post_res.status_code == 202
        task_id = compare_post_res.headers.get("X-Task-ID")
        assert task_id is not None
        # Verify result page via task_id
        compare_result_res = client.get(f"/compare?task_id={task_id}")
        assert compare_result_res.status_code == 200
        assert "Comparison Results" in compare_result_res.text

        # 4. POST /diagnostics/clear
        clear_res = client.post("/diagnostics/clear", data={"csrf_token": "token"}, follow_redirects=True)
        assert clear_res.status_code == 200
