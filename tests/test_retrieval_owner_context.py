"""Whole, scoped context from canonical facts, never a repository scrape."""
import pytest

from app.models.candidate import CandidateProfile, Project
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.services.fact_catalog import FactCatalog
from app.services.fact_retrieval import retrieve_facts


@pytest.fixture
def candidate():
    return CandidateProfile.model_validate({
        "personal": {"name": "Alex Example"},
        "summary_facts": ["Works as a Technical Support Engineer."],
        "experience": [{"company": "Example", "title": "Technical Support Engineer", "facts": [
            "Investigates customer tickets and network incidents.",
            "Documents technical support procedures and ticket escalation."]}],
        "projects": [{"name": "AI lab", "description": "Personal Python application.",
            "technologies": ["Python", "FastAPI"], "facts": [
                "Builds Python FastAPI services with structured JSON responses.",
                "Compares AI model responses in a personal Python project.",
                "Evaluates model accuracy via cross-validation.",
                "Unrelated sentinel detail."]}],
        "skills": {"tools": ["Python", "Docker (basic)"]},
        "education": [{"institution": "Example University", "qualification": "MSc Computer Science",
                       "facts": ["Studied machine learning in an academic project."]}],
    })


def scenario(role="AI/Python Developer", terms="Builds Python FastAPI services with structured JSON responses."):
    job = JobRequest(company="Example", role=role, job_description="Requirements for this position\n" + terms)
    analysis = JobAnalysis(company=job.company, role=role, strong_matches=[], partial_matches=[],
        missing_requirements=[], recommendation="REVIEW", match_level="LOW",
        requirements=[JobRequirement(name=terms, source_quote=terms, priority="mandatory")])
    return job, analysis


def retrieve(candidate, **kwargs):
    job, analysis = scenario()
    return retrieve_facts(job, candidate, analysis, **kwargs)


def owner_entries(result):
    ids = {r["source_id"] for r in result.trace["selected"] if r["reason"] == "owner_context"}
    return [e for e in result.entries if e.source_id in ids]


def test_owner_context_adds_goal_and_evaluation_not_only_keyword_hits(candidate):
    result = retrieve(candidate, top_k=1)
    extra = owner_entries(result)
    assert candidate.projects[0].description in [e.text for e in extra]
    assert "Evaluates model accuracy via cross-validation." in [e.text for e in extra]
    assert all(e.kind == "project" and e.owner_index == 0 for e in extra)
    assert not any(":technology:" in e.source_id or "sentinel" in e.text for e in extra)
    catalog = FactCatalog(candidate)
    assert all(catalog.get(e.source_id) == e for e in result.entries)


def test_context_budget_preserves_identity_anchors_but_not_extra_fragments(candidate):
    result = retrieve(candidate, max_chars=20)
    assert result.entries
    assert all(r["reason"] == "identity_anchor" for r in result.trace["selected"])
    assert not owner_entries(result)


def test_positive_budget_is_enforced_for_whole_context(candidate):
    anchors = retrieve(candidate, top_k=0)
    budget = sum(len(e.text) for e in anchors.entries) + 100
    result = retrieve(candidate, top_k=1, max_chars=budget)
    assert sum(len(e.text) for e in result.entries) <= budget
    assert all(FactCatalog(candidate).get(e.source_id).text == e.text for e in result.entries)


def test_index_collision_with_employment_cannot_import_project(candidate):
    job, analysis = scenario("Technical Support Engineer", "customer tickets network incidents")
    result = retrieve_facts(job, candidate, analysis, top_k=1)
    assert not any(e.kind == "project" for e in result.entries)
    assert not owner_entries(result)


def test_owner_context_is_isolated_from_other_projects(candidate):
    candidate.projects.append(Project(name="Other lab", description="Separate private context.",
                                      facts=["Evaluated unrelated sentinel results."]))
    result = retrieve(candidate, top_k=1)
    assert not any(e.kind == "project" and e.owner_index == 1 for e in result.entries)
    assert not any("sentinel" in e.text for e in result.entries)


def test_context_enrichment_has_a_per_owner_limit(candidate):
    candidate.projects[0].facts += [f"Evaluated experimental model variant {i}." for i in range(20)]
    result = retrieve(candidate, top_k=1)
    assert 1 <= len(owner_entries(result)) <= 5
    assert result == retrieve(candidate, top_k=1)


def test_original_profile_endpoint_can_select_existing_non_matches(candidate):
    job, analysis = scenario("Qzxv", "Zzzqqx")
    tailored = retrieve_facts(job, candidate, analysis, top_k=8)
    assert tailored.trace["mode"] == "no_matches"
    job.tailoring_level = 1
    original = retrieve_facts(job, candidate, analysis, top_k=8)
    assert any(r["reason"] == "profile_order" for r in original.trace["selected"])
    assert all(FactCatalog(candidate).get(e.source_id) == e for e in original.entries)
    assert [e.source_id for e in original.entries[:len(tailored.entries)]] == [
        e.source_id for e in tailored.entries]
