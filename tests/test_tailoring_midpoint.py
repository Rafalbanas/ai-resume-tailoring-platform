import pytest

from app.models.job import JobRequest
from app.services.fact_validator import FactValidator
from scripts.compare_resume_richness import OFFERS, rich_profile, sparse_draft


@pytest.mark.parametrize("role,first_project,featured_skill", [
    ("ML Engineer", "Academic ML thesis", "Machine Learning"),
    ("DevOps Engineer", "Personal operations lab", "Docker"),
    ("Technical Support Engineer", None, "SQL"),
])
def test_midpoint_highlights_role_evidence_without_changing_identity(role, first_project, featured_skill):
    profile = rich_profile()
    if role == "ML Engineer":
        profile.projects.reverse()
    validation = FactValidator(profile)
    draft = sparse_draft(profile)
    job = JobRequest(company="Example", role=role, job_description="Requirements\n" + OFFERS[role])
    target, middle, source = [
        validation.validate(draft, job.model_copy(update={"tailoring_level": level})).resume
        for level in (0, .5, 1)
    ]
    assert middle.core_skills.index(featured_skill) < source.core_skills.index(featured_skill)
    assert middle.professional_summary != source.professional_summary
    assert source.projects[0].name == profile.projects[0].name
    assert source.headline == profile.experience[0].title
    for cv in (target, middle, source):
        assert [e.title for e in cv.experience] == [e.title for e in profile.experience]
        assert "Kubernetes" not in cv.model_dump_json()
    if first_project:
        assert middle.projects[0].name == target.projects[0].name == first_project
        assert middle.section_order.index("projects") < middle.section_order.index("experience")
        assert middle.headline != source.headline
    else:
        assert middle.section_order.index("experience") < middle.section_order.index("projects")
