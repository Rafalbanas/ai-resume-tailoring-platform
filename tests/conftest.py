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
