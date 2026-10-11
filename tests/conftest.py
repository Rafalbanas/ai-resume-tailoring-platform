import pytest

from app.models.candidate import CandidateProfile


@pytest.fixture
def profile() -> CandidateProfile:
    return CandidateProfile.model_validate(
        {
            "personal": {"name": "Jan Test", "email": "jan@example.com"},
            "summary_facts": ["Automates repeatable infrastructure and support workflows with Python."],
            "skills": {"programming": ["Python"], "automation": ["n8n"], "linux": ["Linux"]},
            "experience": [
                {
                    "company": "Example Ltd",
                    "title": "Support Engineer",
                    "start": "2022",
                    "end": "Present",
                    "facts": ["Automated a verified operational workflow with Python."],
                }
            ],
            "education": [],
            "projects": [],
            "certifications": [],
        }
    )


@pytest.fixture
def resume_payload():
    return {
        "headline": "Support Engineer",
        "professional_summary": "Draft text",
        "summary_source_fact_ids": ["summary:0"],
        "core_skills": ["Python", "Kubernetes"],
        "experience": [
            {
                "company": "Example Ltd",
                "title": "Support Engineer",
                "dates": "wrong",
                "bullets": [
                    {
                        "text": "Invented Kubernetes achievement",
                        "source_fact_ids": ["experience:0:fact:0"],
                    }
                ],
            }
        ],
        "education": [],
        "projects": [],
        "certifications": [],
    }


@pytest.fixture(autouse=True)
def isolate_application_runtime(tmp_path, monkeypatch, profile):
    """Never let integration tests start the app against the user's .env/data.

    Individual tests can still override main.get_settings or app.state explicitly.
    The normal runtime uses a synthetic profile, synthetic evidence and mock AI.
    """
    import app.main as app_main
    from app.core.config import Settings
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill

    runtime = tmp_path / "isolated-app-runtime"
    runtime.mkdir()
    (runtime / "master_profile.json").write_text(profile.model_dump_json())
    skills = [VerifiedSkill(id=f"skill_synthetic_{index}", name=name, category="Synthetic test evidence",
                            level="hands_on", verified=True, allowed_in_cv=True,
                            evidence=[SkillEvidence(source_type="manual_verified", source_id=f"manual:test:{index}",
                                                    description=f"Synthetic fixture evidence for {name}")])
              for index, name in enumerate(name for values in profile.skills.values() for name in values)]
    (runtime / "skills.json").write_text(SkillsDocument(skills=skills).model_dump_json())
    settings = Settings(_env_file=None, data_dir=runtime, profile_mode="sample",
                        app_username="audit-tests", app_password="isolated-test-password",
                        csrf_secret="isolated-test-csrf", ai_provider="mock", llm_provider="mock",
                        llm_fallback_provider="none", base_url="http://testserver")
    monkeypatch.setattr(app_main, "get_settings", lambda: settings)
    monkeypatch.setattr(app_main.app, "middleware_stack", None)
