from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.fact_validator import FactValidator


def test_fact_validator_rejects_unknown_skill(profile, resume_payload):
    resume = TailoredResume.model_validate(resume_payload)
    job = JobRequest(company="Acme", role="Engineer", job_description="A sufficiently complete job description for testing.")
    result = FactValidator(profile).validate(resume, job)
    assert "Kubernetes" not in result.resume.model_dump_json()
    assert any("Kubernetes" in warning for warning in result.warnings)
    assert result.resume.experience[0].bullets[0].text == profile.experience[0].facts[0]


def test_fact_validator_rejects_fake_certification(profile, resume_payload):
    resume_payload["certifications"] = [{"name": "CCNA", "issuer": "Cisco", "date": "2026"}]
    result = FactValidator(profile).validate(
        TailoredResume.model_validate(resume_payload),
        JobRequest(company="Acme", role="Engineer", job_description="A sufficiently complete job description for testing."),
    )
    assert not result.resume.certifications
    assert any("CCNA" in warning for warning in result.warnings)
