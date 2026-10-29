import hashlib
import json
from types import SimpleNamespace

import pytest

from app.models.job import JobAnalysis, JobRequest
from app.models.resume import TailoredResume, WorkflowResponse
from app.services.storage import DraftDataError, Storage, safe_filename


def test_safe_filename():
    assert safe_filename("../../HSBC: App Support") == "hsbc-app-support"
    assert safe_filename("Łódź / DevOps") == "odz-devops"


@pytest.mark.parametrize("kind", ["pdf", "docx"])
@pytest.mark.parametrize("company,role", [
    ("Square One Resources Sp. z o.o.", "Supply Chain Planning Systems Consultant SQL Data Analysis OMP Platform"),
    ("Bardzo długa nazwa przedsiębiorstwa S.A.", "Senior Software Engineer Kubernetes Python Infrastructure"),
    ("X" * 150, "Y" * 150),
    ("株式会社", "開発者"),
])
def test_download_filename_limits_and_unique_legacy_exports(tmp_path, kind, company, role):
    storage = Storage(tmp_path)
    metadata = {"date": "2026-10-21", "company": company, "role": role}
    names = []
    for slug in ("2026-10-21_legacy-long-name", "2026-10-21_legacy-long-name_2"):
        (storage.generated_dir / slug).mkdir()
        name = storage.download_filename(slug, kind, metadata)
        assert len(name) <= 50
        assert name.isascii()
        assert name.startswith("26-10-21_")
        assert name.endswith(f".{kind}")
        assert name == storage.download_filename(slug, kind, metadata)
        names.append(name)
    assert names[0] != names[1]
    if company.startswith("Square"):
        assert names[0].startswith("26-10-21_square-one_supply-plan-sql")
        if kind == "pdf":
            assert "-omp_" in names[0]


def test_download_filename_extends_identifier_on_collision(tmp_path, monkeypatch):
    storage = Storage(tmp_path)
    for slug in ("first", "second"):
        (storage.generated_dir / slug).mkdir()
    real_sha256 = hashlib.sha256

    def colliding_sha256(value):
        class Digest:
            def hexdigest(self):
                return "abcdef" + real_sha256(value).hexdigest()[6:]
        return Digest()

    monkeypatch.setattr("app.services.storage.hashlib.sha256", colliding_sha256)
    metadata = {"date": "2026-10-21", "company": "Square One Resources", "role": "Supply Chain Planning SQL OMP"}
    first = storage.download_filename("first", "pdf", metadata)
    second = storage.download_filename("second", "pdf", metadata)
    assert first != second
    assert len(first) <= 50
    assert len(second) <= 50
    assert len(first.rsplit("_", 1)[1].split(".")[0]) > 6


@pytest.mark.parametrize("kind", ["pdf", "docx"])
async def test_download_response_uses_short_filename(tmp_path, resume_payload, monkeypatch, kind):
    from app.routes import web

    storage = Storage(tmp_path)
    job = JobRequest(company="Square One Resources Sp. z o.o.",
                     role="Supply Chain Planning Systems Consultant SQL Data Analysis OMP Platform",
                     job_description="A sufficiently complete job description for testing.")
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation="APPLY", match_level="HIGH")
    slug, folder = storage.save_application(job, analysis, TailoredResume.model_validate(resume_payload), [])
    (folder / f"resume.{kind}").write_bytes(b"synthetic-export")
    state = SimpleNamespace(storage=storage, profile=None, settings=SimpleNamespace(csrf_secret="test"),
                            auth_store=SimpleNamespace(username="test"))
    request = SimpleNamespace(app=SimpleNamespace(state=state), headers={})
    monkeypatch.setattr(web, "guard", lambda request: None)
    monkeypatch.setattr(web, "summary_review", lambda *args: {"required": False})
    response = await web.download(request, slug, kind)
    assert response.path == folder / f"resume.{kind}"
    name = response.headers["content-disposition"].split('filename="')[1].rstrip('"')
    assert len(name) <= 50
    assert name.endswith(f".{kind}")
    assert "_square-one_supply-plan-sql" in name


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


def test_draft_roundtrip_recovers_oversized_analysis_summary(tmp_path, resume_payload):
    storage = Storage(tmp_path)
    job = JobRequest(company="Acme", role="Engineer", job_description="A complete job description for testing.")
    analysis = JobAnalysis(
        company="Acme", role="Engineer", strong_matches=[], partial_matches=[], missing_requirements=[],
        supported_keywords=[], unsupported_keywords=[], recommendation="RETRY", match_level="UNRELIABLE",
        reasoning_summary="Review required.",
    )
    analysis.reasoning_summary = "x" * 3062
    response = WorkflowResponse(analysis=analysis, resume=TailoredResume.model_validate(resume_payload))
    response.resume._bullet_attestations = ["signed-test-attestation"]
    draft_id = storage.save_draft(job, response)
    path = storage.drafts_dir / f"{draft_id}.json"
    payload = json.loads(path.read_text())
    assert len(payload["response"]["analysis"]["reasoning_summary"]) == 2000
    payload["response"]["analysis"]["reasoning_summary"] = "x" * 3062
    path.write_text(json.dumps(payload))
    restored_job, restored = storage.load_draft(draft_id)
    assert restored_job == job
    assert restored.analysis.reasoning_summary == "x" * 2000
    assert restored.analysis.recommendation == analysis.recommendation
    assert restored.resume._bullet_attestations == ["signed-test-attestation"]
    assert storage.analysis_history()[0]["view_url"] == f"/analysis/{draft_id}"
    # Legacy recovery remains read-only.
    assert len(json.loads(path.read_text())["response"]["analysis"]["reasoning_summary"]) == 3062



@pytest.mark.parametrize("content", ['{', '[]', '{}', '{"response": null}',
                                      '{"response": {"analysis": []}}'])
def test_invalid_draft_is_distinct_from_missing_draft(tmp_path, content):
    storage = Storage(tmp_path)
    draft_id = "a" * 32
    with pytest.raises(FileNotFoundError):
        storage.load_draft(draft_id)
    path = storage.drafts_dir / f"{draft_id}.json"
    path.write_text(content)
    with pytest.raises(DraftDataError):
        storage.load_draft(draft_id)
    assert path.read_text() == content



@pytest.mark.parametrize("failure", ["invalid_model", "readback", "replace"])
def test_draft_save_does_not_publish_failed_results(tmp_path, resume_payload, monkeypatch, failure):
    storage = Storage(tmp_path)
    job = JobRequest(company="Acme", role="Engineer", job_description="A complete job description for testing.")
    analysis = JobAnalysis(
        company="Acme", role="Engineer", strong_matches=[], partial_matches=[], missing_requirements=[],
        supported_keywords=[], unsupported_keywords=[], recommendation="RETRY", match_level="UNRELIABLE",
        reasoning_summary="Review required.",
    )
    response = WorkflowResponse(analysis=analysis, resume=TailoredResume.model_validate(resume_payload))
    if failure == "invalid_model":
        response.resume.headline = "x" * 141
    elif failure == "readback":
        def fail_readback(_):
            raise DraftDataError("Simulated unreadable draft")
        monkeypatch.setattr(storage, "load_draft", fail_readback)
    else:
        def fail_replace(*_):
            raise OSError("Simulated disk error")
        monkeypatch.setattr("app.services.storage.os.replace", fail_replace)
    with pytest.raises((DraftDataError, OSError)):
        storage.save_draft(job, response)
    assert list(storage.drafts_dir.iterdir()) == []
