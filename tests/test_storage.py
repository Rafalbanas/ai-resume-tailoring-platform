from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume
from app.services.storage import Storage, safe_filename


def test_safe_filename():
    assert safe_filename("../../HSBC: App Support") == "hsbc-app-support"
    assert safe_filename("Łódź / DevOps") == "odz-devops"


def test_storage(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    job = JobRequest(
        company="Acme",
        role="Engineer",
        job_url="https://jobs.example.com/engineer",
        job_description="A sufficiently complete job description for testing.",
    )
    analysis = JobAnalysis(
        company="Acme", role="Engineer", strong_matches=[], partial_matches=[], missing_requirements=[],
        supported_keywords=[], unsupported_keywords=[], recommendation="APPLY", match_level="HIGH", reasoning_summary="Good fit."
    )
    slug, folder = storage.save_application(job, analysis, TailoredResume.model_validate(resume_payload), [])
    assert folder.is_dir()
    assert storage.history()[0]["slug"] == slug
    assert storage.history()[0]["job_url"] == "https://jobs.example.com/engineer"
    (folder / "resume.pdf").write_bytes(b"%PDF-test")
    assert storage.artifact(slug, "resume.pdf").read_bytes() == b"%PDF-test"


def test_history_stores_only_safe_photo_setting(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    job = JobRequest(company="Acme", role="Engineer", job_description="A complete job description for testing.")
    analysis = JobAnalysis(
        company="Acme", role="Engineer", strong_matches=[], partial_matches=[], missing_requirements=[],
        supported_keywords=[], unsupported_keywords=[], recommendation="APPLY", match_level="HIGH",
        reasoning_summary="Good fit.",
    )
    slug, _ = storage.save_application(
        job,
        analysis,
        TailoredResume.model_validate(resume_payload),
        [],
        template_name="modern_sidebar",
        photo_enabled=True,
    )
    _, _, _, metadata = storage.load_application(slug)
    assert metadata["photo_enabled"] is True
    assert metadata["template_name"] == "modern_sidebar"
    assert "base64" not in str(metadata).casefold()
