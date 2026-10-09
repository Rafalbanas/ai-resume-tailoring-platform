from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.templating import Jinja2Templates

import app.routes.web as web_routes
from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator
from app.services.profile_photo import ProfilePhotoStore


class NoopLimiter:
    def check(self, _key: str) -> None:
        return None


def test_interests_candidate_profile_routes(tmp_path, profile, monkeypatch):
    monkeypatch.setattr(web_routes, "guard", lambda _request: None)
    monkeypatch.setattr(web_routes, "validate_csrf", lambda *_: None)

    profile_file = tmp_path / "master_profile.json"
    profile_file.write_text(profile.model_dump_json(indent=2), encoding="utf-8")

    app = FastAPI()
    app.include_router(web_routes.router)
    app.state.templates = Jinja2Templates(directory="templates")
    app.state.settings = SimpleNamespace(
        profile_photo_max_bytes=5_000_000,
        app_build_sha="test",
        app_build_timestamp="now",
        csrf_secret="secret",
        master_profile_path=profile_file,
    )
    app.state.limiter = NoopLimiter()
    app.state.profile = profile
    app.state.profile_photo = ProfilePhotoStore(tmp_path / "photo")

    client = TestClient(app)

    # 1. GET /profile renders interests section
    res = client.get("/profile")
    assert res.status_code == 200
    assert "Interests & Passions" in res.text

    # 2. Add an interest
    add_res = client.post(
        "/profile/interests/add",
        data={
            "name": "Gravel cycling",
            "category": "Sports",
            "allowed_in_cv": "on",
            "enabled": "on",
            "csrf_token": "token",
        },
        follow_redirects=True,
    )
    assert add_res.status_code == 200
    assert "Gravel cycling" in add_res.text
    assert any(i.name == "Gravel cycling" for i in app.state.profile.interests)

    # 3. Toggle interest
    interest_id = "gravel_cycling"
    toggle_res = client.post(
        f"/profile/interests/{interest_id}/toggle",
        data={"csrf_token": "token"},
        follow_redirects=True,
    )
    assert toggle_res.status_code == 200
    toggled = next(i for i in app.state.profile.interests if i.id == interest_id)
    assert toggled.enabled is False

    # 4. Delete interest
    del_res = client.post(
        f"/profile/interests/{interest_id}/delete",
        data={"csrf_token": "token"},
        follow_redirects=True,
    )
    assert del_res.status_code == 200
    assert not any(i.id == interest_id for i in app.state.profile.interests)


def test_interests_rendered_in_sidebar_and_excluded_from_ats(profile, resume_payload, tmp_path):
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    resume = TailoredResume.model_validate(resume_payload)
    resume.interests = ["Gravel cycling", "Speciality coffee"]

    modern_html = generator.render_html(resume, profile, template_name="modern_sidebar")
    assert "Interests" in modern_html
    assert "Gravel cycling" in modern_html
    assert "Speciality coffee" in modern_html

    ats_html = generator.render_html(resume, profile, template_name="ats_classic")
    assert "interests-block" not in ats_html
    assert "Gravel cycling" not in ats_html


def test_interests_removed_first_on_overflow(profile, resume_payload, tmp_path):
    from app.models.resume import ResumeBullet, ResumeExperience

    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    resume = TailoredResume.model_validate(resume_payload)
    resume.interests = ["Gravel cycling"]
    resume.core_skills = [
        "Linux",
        "Docker",
        "Python",
        "FastAPI",
        "CI/CD",
        "Git",
        "Nginx",
        "PostgreSQL",
        "Redis",
        "Bash",
        "Terraform",
        "Kubernetes",
        "Ansible",
        "AWS",
        "GCP",
        "Monitoring",
    ]
    resume.experience = [
        ResumeExperience(
            company=f"Company {i}",
            title="Platform Engineer",
            dates="2022-2024",
            bullets=[
                ResumeBullet(
                    text="Configured Linux VPS and systemd services with production reverse SSH tunneling." * 2,
                    source_fact_ids=["experience:0:fact:0"],
                )
                for _ in range(4)
            ],
        )
        for i in range(3)
    ]
    resume.professional_summary = (
        "Very long summary text describing platform engineering achievements and technical solutions in detail." * 5
    )

    fitted, actions = generator.fit_resume(resume, profile)
    assert any("removed interests" in a for a in actions)
    assert fitted.interests == []


def test_thesis_subline_when_thesis_not_in_projects(profile, resume_payload):
    # Setup candidate with MSc including thesis
    payload = profile.model_dump(mode="json")
    payload["education"] = [
        {
            "institution": "Politechnika Krakowska",
            "qualification": "Master of Science in Computer Science",
            "dates": "2022 — 2024",
            "degree": "Master of Science in Computer Science",
            "university": "Politechnika Krakowska",
            "year": "2024",
            "specialisation": "Data Science & Machine Learning",
            "thesis_title": "ML-based FTP estimation from cycling telemetry",
            "thesis_summary": "Engineered an end-to-end Machine Learning pipeline predicting FTP from telemetry.",
            "thesis_project_id": "cycling-telemetry-ftp",
            "facts": ["Graduated with MSc in Computer Science."],
        }
    ]
    # Projects: only Linux VPS and AI Tailor
    payload["projects"] = [
        {
            "name": "Linux VPS",
            "description": "Maintains self-hosted Linux VPS.",
            "technologies": ["Linux", "Docker"],
            "facts": ["Maintains self-hosted services using SSH and Linux administration."],
        },
        {
            "name": "AI Resume Platform",
            "description": "FastAPI tailoring platform.",
            "technologies": ["Python", "FastAPI"],
            "facts": ["Built a verified FastAPI platform."],
        },
    ]
    cand = CandidateProfile.model_validate(payload)
    platform_job = JobRequest(
        company="Tech Corp",
        role="Platform Engineer",
        job_description="Seeking a Platform Engineer with Linux, Docker, and automation skills.",
    )
    validator = FactValidator(cand)
    result = validator.validate(
        TailoredResume(
            headline="Platform Engineer",
            professional_summary="",
            core_skills=[],
            experience=[],
        ),
        platform_job,
    )
    # Thesis is NOT in projects
    assert not any("thesis" in p.name.casefold() for p in result.resume.projects)
    # Education has thesis subline
    edu = result.resume.education[0]
    assert "Thesis: ML-based FTP estimation from cycling telemetry" in edu.thesis_subline
    assert "Specialisation: Data Science & Machine Learning" in edu.specialisation


def test_thesis_subline_suppressed_when_thesis_is_in_projects(profile):
    payload = profile.model_dump(mode="json")
    payload["education"] = [
        {
            "institution": "Politechnika Krakowska",
            "qualification": "Master of Science in Computer Science",
            "dates": "2022 — 2024",
            "degree": "Master of Science in Computer Science",
            "university": "Politechnika Krakowska",
            "year": "2024",
            "specialisation": "Data Science & Machine Learning",
            "thesis_title": "ML-based FTP estimation from cycling telemetry",
            "thesis_summary": "Engineered an end-to-end Machine Learning pipeline predicting FTP.",
            "thesis_project_id": "cycling-telemetry-ftp",
            "facts": ["Graduated with MSc in Computer Science."],
        }
    ]
    payload["projects"] = [
        {
            "name": "Python ML thesis project",
            "description": "ML-based FTP estimation from cycling telemetry.",
            "technologies": ["Python", "scikit-learn", "XGBoost", "pandas"],
            "facts": ["Engineered ML pipeline for cycling telemetry."],
        },
        {
            "name": "Linux VPS",
            "description": "Maintains Linux VPS.",
            "technologies": ["Linux"],
            "facts": ["Maintains self-hosted services."],
        },
    ]
    cand = CandidateProfile.model_validate(payload)
    ml_job = JobRequest(
        company="AI Labs",
        role="Machine Learning Engineer",
        job_description="Machine Learning Engineer required with Python, scikit-learn, XGBoost, pandas, regression models.",
    )
    validator = FactValidator(cand)
    result = validator.validate(
        TailoredResume(
            headline="Machine Learning Engineer",
            professional_summary="",
            core_skills=[],
            experience=[],
        ),
        ml_job,
    )
    # Thesis project IS selected in projects!
    project_names = [p.name for p in result.resume.projects]
    assert "Python ML thesis project" in project_names
    assert project_names[0] == "Python ML thesis project"

    # Education thesis subline is SUPPRESSED to prevent duplicate claims!
    edu = result.resume.education[0]
    assert edu.thesis_subline == ""
    assert "Specialisation: Data Science & Machine Learning" in edu.specialisation
