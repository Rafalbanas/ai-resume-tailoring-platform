import asyncio
import json

import httpx
import pytest

from app.core.config import Settings
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.models.resume import ResumeBullet, ResumeExperience, TailoredResume, WorkflowResponse
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_validator import FactValidator
from app.services.ollama_draft_review import review_draft, sign_bullet, valid_bullet_attestation
from app.services.ollama_provider import OllamaProvider
from app.services.storage import Storage


def inputs(profile):
    job = JobRequest(company="Example", role="Support Engineer",
                     job_description="Requirements\nExperience with Python\nExperience with Docker")
    analysis = JobAnalysis(company=job.company, role=job.role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation="REVIEW", match_level="LOW",
                           analysis_method="llm_validated", requirements=[
                               JobRequirement(name="Python", source_quote="Experience with Python", status="strong",
                                              source_fact_ids=["experience:0:fact:0"], reason="Documented Python automation."),
                               JobRequirement(name="Docker", source_quote="Experience with Docker", status="missing",
                                              reason="Not confirmed.")])
    analysis = AnalysisValidator(profile).validate(analysis, f"{job.role}\n{job.job_description}", semantic=True)
    resume = TailoredResume(headline="Support Engineer", professional_summary=profile.summary_facts[0],
                            summary_source_fact_ids=["summary:0"], core_skills=["Python"], experience=[
                                ResumeExperience(company="Example Ltd", title="Support Engineer", dates="2022 – Present",
                                                 bullets=[ResumeBullet(text="Automated support workflows with Python.",
                                                                       source_fact_ids=["experience:0:fact:0"])])])
    return job, analysis, resume


@pytest.mark.asyncio
async def test_full_workflow_thinks_only_in_the_final_review(profile):
    from tests.test_ollama_provider import analysis_payload, job, resume_payload
    requests = []
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        stage = json.loads(body["messages"][1]["content"])["stage"]
        answer = {"analyze_job": analysis_payload, "tailor_resume": resume_payload}.get(stage)
        content = answer() if answer else verdict(body)
        return httpx.Response(200, json={"message": {"content": json.dumps(content)}, "done_reason": "stop"})
    p = OllamaProvider(Settings(_env_file=None, csrf_secret="review-key"), transport=httpx.MockTransport(handler))
    response = await p.tailor(job(), profile)
    assert [json.loads(r["messages"][1]["content"])["stage"] for r in requests] == [
        "analyze_job", "tailor_resume", "review_draft"]
    assert [r["think"] for r in requests] == [False, False, True]
    assert [m["thinking_requested"] for m in response.call_metrics] == [False, False, True]
    from app.services.resilient_provider import ResilientAIProvider
    response.analysis.requirements[-1].reason = "First-pass explanation."
    router = ResilientAIProvider({"ollama": p}, default_primary="ollama", default_fallback="none")
    renewed = await router.retailor(job(), profile, response.analysis, requested_provider="ollama")
    assert renewed.analysis.requirements[-1].reason != "First-pass explanation."
    assert response.analysis.requirements[-1].reason == "First-pass explanation."


def verdict(body):
    data = json.loads(body["messages"][1]["content"])
    return {"gaps": [{"id": g["id"], "status": "missing", "facts": [],
                      "reason": "The supplied profile does not document Docker use; this does not establish inability."}
                     for g in data["gaps"]],
            "bullets": [{"id": b["id"], "supported": True, "relevant": True} for b in data["bullets"]]}


@pytest.mark.asyncio
async def test_review_is_one_bounded_thinking_call_and_preserves_approved_paraphrase(profile, tmp_path):
    job, analysis, resume = inputs(profile)
    requests = []
    async def handler(request):
        body = json.loads(request.content)
        requests.append(body)
        return httpx.Response(200, json={"message": {"content": json.dumps(verdict(body)), "thinking": "Review."},
                                        "done": True, "done_reason": "stop"})
    p = OllamaProvider(Settings(_env_file=None, csrf_secret="review-key"), transport=httpx.MockTransport(handler))
    reviewed = await review_draft(p, resume, analysis, job, profile)
    assert len(requests) == 1
    assert requests[0]["think"] is True and requests[0]["options"]["num_predict"] == 2048
    assert p.call_metrics[-1]["stage"] == "review_draft" and p.call_metrics[-1]["review_outcome"] == "accepted"
    assert valid_bullet_attestation(reviewed.experience[0].bullets[0], reviewed, profile, "review-key")
    assert "does not establish inability" in next(r.reason for r in analysis.requirements if r.name == "Docker")
    assert next(r.status for r in analysis.requirements if r.name == "Docker") == "missing"
    storage = Storage(tmp_path)
    draft_id = storage.save_draft(job, WorkflowResponse(analysis=analysis, resume=reviewed))
    _, restored = storage.load_draft(draft_id)
    checked = FactValidator(profile, analysis=analysis, review_key="review-key").validate(restored.resume, job).resume
    assert checked.experience[0].bullets[0].text == "Automated support workflows with Python."
    slug, _ = storage.save_application(job, analysis, checked, [])
    _, saved, generated, _ = storage.load_application(slug)
    for document in (saved, generated):
        assert valid_bullet_attestation(document.experience[0].bullets[0], document, profile, "review-key")


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["length", "timeout", "unknown_id", "duplicate", "unknown_fact", "no_evidence"])
async def test_failed_review_keeps_first_pass_without_retries_or_approval(profile, monkeypatch, failure):
    from app.services import ollama_draft_review
    job, analysis, resume = inputs(profile)
    before = analysis.model_dump()
    calls = []
    async def handler(request):
        calls.append(request)
        body = json.loads(request.content)
        answer = verdict(body)
        if failure == "timeout":
            await asyncio.sleep(1)
        if failure == "unknown_id":
            answer["bullets"][0]["id"] = "invented"
        if failure == "duplicate":
            answer["bullets"] *= 2
        if failure in {"unknown_fact", "no_evidence"}:
            answer["gaps"][0].update(status="strong", facts=["invented"] if failure == "unknown_fact" else [])
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}, "done": True,
                                        "done_reason": "length" if failure == "length" else "stop"})
    monkeypatch.setattr(ollama_draft_review, "REVIEW_TIMEOUT_SECONDS", 0.01)
    p = OllamaProvider(Settings(_env_file=None, csrf_secret="review-key"), transport=httpx.MockTransport(handler))
    reviewed = await review_draft(p, resume, analysis, job, profile)
    assert reviewed is resume and not reviewed._bullet_attestations
    assert analysis.model_dump() == before and len(calls) == 1


@pytest.mark.parametrize("change", ["text", "citation", "profile", "key", "forged"])
def test_bullet_approval_is_bound_to_exact_wording_sources_profile_and_key(profile, change):
    job, analysis, resume = inputs(profile)
    bullet = resume.experience[0].bullets[0]
    resume._bullet_attestations = [sign_bullet(bullet, profile, "review-key")]
    if change == "text":
        bullet.text = "Architected advanced production Kubernetes systems."
    elif change == "citation":
        bullet.source_fact_ids = ["summary:0"]
    elif change == "profile":
        profile.experience[0].facts = ["One introductory Python exercise."]
    elif change == "forged":
        resume._bullet_attestations = ["approved-by-model"]
    key = "another-key" if change == "key" else "review-key"
    assert not valid_bullet_attestation(bullet, resume, profile, key)
    checked = FactValidator(profile, analysis=analysis, review_key=key).validate(resume, job).resume
    assert all(b.text != bullet.text for e in checked.experience for b in e.bullets)


@pytest.mark.asyncio
async def test_review_drops_irrelevant_description_and_cannot_move_facts_between_employers(profile):
    job, analysis, resume = inputs(profile)
    resume.experience[0].bullets.append(ResumeBullet(text=profile.experience[0].facts[0],
                                                   source_fact_ids=["experience:0:fact:0"]))
    async def handler(request):
        answer = verdict(json.loads(request.content))
        answer["bullets"][0]["relevant"] = False
        return httpx.Response(200, json={"message": {"content": json.dumps(answer)}, "done_reason": "stop"})
    p = OllamaProvider(Settings(_env_file=None, csrf_secret="review-key"), transport=httpx.MockTransport(handler))
    reviewed = await review_draft(p, resume, analysis, job, profile)
    assert len(reviewed.experience[0].bullets) == 1
    assert reviewed.experience[0].bullets[0].text == profile.experience[0].facts[0]
    reviewed.experience[0].company = "Invented company"
    checked = FactValidator(profile, analysis=analysis, review_key="review-key").validate(reviewed, job).resume
    assert checked.experience[0].company == "Example Ltd"


@pytest.mark.asyncio
async def test_optional_review_is_skipped_when_primary_calls_used_most_of_task_budget(profile):
    job, analysis, resume = inputs(profile)
    p = OllamaProvider(Settings(_env_file=None))
    token = p._run_metrics.set([{"total_ms": 500_000}])
    try:
        assert await review_draft(p, resume, analysis, job, profile) is resume
        assert not p.call_metrics
    finally:
        p._run_metrics.reset(token)
