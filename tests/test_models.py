from pathlib import Path

import pytest
from pydantic import ValidationError

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis
from app.models.resume import TailoredResume


def test_master_profile_validation():
    profile = CandidateProfile.model_validate_json(Path("data/master_profile.json").read_text())
    assert "kubernetes" not in profile.skill_set()


def test_job_analysis_schema():
    model = JobAnalysis.model_validate(
        {
            "company": "Acme",
            "role": "Engineer",
            "strong_matches": [],
            "partial_matches": [],
            "missing_requirements": [],
            "supported_keywords": [],
            "unsupported_keywords": [],
            "recommendation": "APPLY",
            "match_level": "HIGH",
            "reasoning_summary": "Verified facts align with the role.",
        }
    )
    assert model.match_level == "HIGH"
    with pytest.raises(ValidationError):
        JobAnalysis.model_validate({**model.model_dump(), "match_level": "92%"})


def test_resume_schema(resume_payload):
    assert TailoredResume.model_validate(resume_payload).experience[0].bullets
