import json

import pytest
from pydantic import ValidationError

from app.models.job import JobAnalysis, JobRequest, MatchLevel, Recommendation
from app.models.resume import TailoredResume
from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_validator import FactValidator
from app.services.resume_editor import apply_resume_edits
from app.services.skills_bank import SkillsBank, SkillsConfigurationError


def skill(
    name: str,
    *,
    level: str = "hands_on",
    verified: bool = True,
    allowed: bool = True,
    enabled: bool = True,
    aliases: list[str] | None = None,
    priority: int = 8,
    category: str = "Engineering",
) -> VerifiedSkill:
    evidence = []
    if verified:
        evidence = [
            SkillEvidence(
                source_type="manual_verified",
                source_id=f"manual:{name.casefold().replace(' ', '_')}",
                description="Explicit test verification",
            )
        ]
    return VerifiedSkill(
        id="skill_" + "_".join("".join(char if char.isalnum() else " " for char in name.casefold()).split()),
        name=name,
        category=category,
        level=level,
        verified=verified,
        allowed_in_cv=allowed,
        enabled=enabled,
        aliases=aliases or [],
        evidence=evidence,
        priority=priority,
    )


def bank(tmp_path, profile, skills: list[VerifiedSkill], name: str = "skills.json") -> SkillsBank:
    path = tmp_path / name
    path.write_text(SkillsDocument(skills=skills).model_dump_json(), encoding="utf-8")
    return SkillsBank(path, profile)


def analysis(**updates) -> JobAnalysis:
    values = dict(
        company="Example",
        role="Engineer",
        strong_matches=[],
        partial_matches=[],
        missing_requirements=[],
        supported_keywords=[],
        unsupported_keywords=[],
        recommendation=Recommendation.SKIP,
        match_level=MatchLevel.LOW,
        reasoning_summary="Initial",
    )
    values.update(updates)
    return JobAnalysis(**values)


def resume(skills: list[str], ids: list[str] | None = None) -> TailoredResume:
    return TailoredResume(
        headline="Engineer",
        professional_summary="Automates repeatable infrastructure and support workflows with Python.",
        summary_source_fact_ids=["summary:0"],
        core_skills=skills,
        selected_skill_ids=ids or [],
        experience=[],
    )


def job(text: str) -> JobRequest:
    return JobRequest(company="Example", role="Engineer", job_description=text.ljust(30, "."))


def test_verified_skill_enters_strong_match(tmp_path, profile):
    value = skill("Python")
    store = bank(tmp_path, profile, [value])
    result = AnalysisValidator(profile, store).validate(analysis(strong_skill_ids=[value.id]))
    assert result.strong_matches == ["Python"]
    assert result.match_evidence["Python"] == ["Explicit test verification"]


def test_disabled_skill_does_not_enter_cv(tmp_path, profile):
    value = skill("Python", enabled=False)
    store = bank(tmp_path, profile, [value])
    result = FactValidator(profile, store).validate(resume(["Python"], [value.id]), job("Python automation"))
    assert "Python" not in result.resume.core_skills


def test_learning_skill_is_missing_not_experience(tmp_path, profile):
    rag = skill("RAG", level="learning", verified=False, allowed=False)
    store = bank(tmp_path, profile, [rag])
    result = AnalysisValidator(profile, store).validate(analysis(learning_skill_ids=[rag.id]))
    assert not result.strong_matches
    assert result.learning_matches == ["RAG"]
    assert "RAG (Learning)" in result.missing_requirements


def test_basic_skill_uses_basic_wording(tmp_path, profile):
    docker = skill("Docker", level="basic")
    store = bank(tmp_path, profile, [docker])
    result = FactValidator(profile, store).validate(resume([], [docker.id]), job("Docker containers"))
    assert result.resume.core_skills == ["Basic Docker"]


def test_unsupported_skill_stays_missing(tmp_path, profile):
    store = bank(tmp_path, profile, [skill("Python")])
    result = AnalysisValidator(profile, store).validate(analysis(strong_matches=["Kubernetes"]))
    assert "Kubernetes" in result.missing_requirements
    assert "Kubernetes" not in result.strong_matches


def test_alias_matching(tmp_path, profile):
    ad = skill("Active Directory", aliases=["AD", "Microsoft Active Directory"])
    store = bank(tmp_path, profile, [ad])
    assert store.find("AD") == ad
    assert store.mentioned(ad, "Hands-on Microsoft Active Directory. Administration required.")


def test_verified_requires_evidence():
    with pytest.raises(ValidationError, match="requires evidence"):
        VerifiedSkill(
            id="skill_python", name="Python", category="Engineering", level="hands_on",
            verified=True, allowed_in_cv=True,
        )


def test_manual_verified_evidence_is_valid(tmp_path, profile):
    store = bank(tmp_path, profile, [skill("Python")])
    assert store.get("skill_python").verified


def test_ai_cannot_create_unknown_verified_skill(tmp_path, profile):
    store = bank(tmp_path, profile, [skill("Python")])
    result = FactValidator(profile, store).validate(resume(["Made Up Cloud"]), job("Made Up Cloud platform"))
    assert "Made Up Cloud" not in result.resume.core_skills
    assert any("Unsupported AI fact" in warning for warning in result.warnings)


@pytest.mark.parametrize("unsupported", ["PostgreSQL", "Azure Data Factory", "Elasticsearch", "Kubernetes", "Ansible"])
def test_truth_lock_blocks_unsupported_technology(tmp_path, profile, unsupported):
    store = bank(tmp_path, profile, [skill("Python")])
    result = FactValidator(profile, store).validate(resume([unsupported]), job(f"Requires {unsupported} experience"))
    assert all(unsupported not in value for value in result.resume.core_skills)


def test_verified_ai_ml_skill_can_enter_cv(tmp_path, profile):
    ollama = skill("Ollama", category="AI / ML")
    store = bank(tmp_path, profile, [ollama])
    result = FactValidator(profile, store).validate(resume([], [ollama.id]), job("Local Ollama LLM integration"))
    assert "Hands-on Ollama" in result.resume.core_skills


def test_rag_learning_never_enters_cv(tmp_path, profile):
    rag = skill("Retrieval-Augmented Generation (RAG)", level="learning", verified=False, allowed=False)
    store = bank(tmp_path, profile, [rag])
    result = FactValidator(profile, store).validate(resume(["RAG"], [rag.id]), job("RAG and vector retrieval"))
    assert result.resume.core_skills == []


def test_cv_selects_only_relevant_before_fill(tmp_path, profile):
    values = [skill("Windows Server", priority=5), skill("Ollama", priority=4), skill("Python", priority=3)]
    store = bank(tmp_path, profile, values)
    selected = store.select_for_job([], "Windows Server administrator", minimum=1)
    assert selected[0].name == "Windows Server"
    assert "Ollama" not in [value.name for value in selected]


def test_cv_has_at_most_16_skills(tmp_path, profile):
    values = [skill(f"Technology {index}") for index in range(20)]
    store = bank(tmp_path, profile, values)
    selected = store.select_for_job([value.id for value in values], "Technology", maximum=16)
    assert len(selected) == 16


def test_production_never_uses_example_bank(tmp_path, profile):
    example = tmp_path / "skills.example.json"
    example.write_text(json.dumps({"version": 1, "skills": []}), encoding="utf-8")
    with pytest.raises(SkillsConfigurationError, match="Production cannot use"):
        SkillsBank(example, profile, "production")
    with pytest.raises(SkillsConfigurationError, match="missing"):
        SkillsBank(tmp_path / "skills.json", profile, "production")


def test_different_jobs_select_different_skills(tmp_path, profile):
    values = [
        skill("Windows Server", aliases=["Windows"]), skill("Linux", aliases=["Unix"]),
        skill("Machine Learning", aliases=["ML"], category="AI / ML"), skill("Python"),
        skill("PowerShell"), skill("Technical Support"), skill("SQL"), skill("Ollama", category="AI / ML"),
    ]
    store = bank(tmp_path, profile, values)
    windows = {item.id for item in store.select_for_job([], "Windows PowerShell administrator", minimum=2)}
    ai = {item.id for item in store.select_for_job([], "Python ML and Ollama engineer", minimum=2)}
    assert windows != ai
    assert "skill_windows_server" in windows
    assert "skill_machine_learning" in ai


def test_manual_skill_edit_replaces_generated_ids(tmp_path, profile):
    python = skill("Python")
    linux = skill("Linux")
    store = bank(tmp_path, profile, [python, linux])
    generated = resume(["Hands-on Python", "Hands-on Linux"], [python.id, linux.id])
    edited = apply_resume_edits(generated, {"core_skills": "Linux"})
    result = FactValidator(profile, store).validate(edited, job("Linux support engineer"))
    assert result.resume.selected_skill_ids == [linux.id]


def test_headline_blocks_job_requirements_and_uses_verified_skill_ids(tmp_path, profile):
    python = skill("Python")
    linux = skill("Linux")
    store = bank(tmp_path, profile, [python, linux])
    hostile = resume(
        ["PostgreSQL", "Azure Data Factory", "GitLab CI/CD", "Elasticsearch", "Java"],
        [python.id, linux.id],
    )
    hostile.headline = (
        "Platform Engineer | Linux & Bash Automation | PostgreSQL & Azure Data Factory | "
        "GitLab CI/CD | Elasticsearch | Java"
    )
    platform = JobRequest(
        company="Example",
        role="Platform Engineer",
        job_description=(
            "Requires PostgreSQL, Azure Data Factory, GitLab CI/CD, Elasticsearch, Java, Linux and Python."
        ),
    )

    result = FactValidator(profile, store).validate(hostile, platform)

    assert result.resume.headline == "Platform Engineer | Python | Linux"
    serialized = result.resume.model_dump_json()
    for unsupported in ("PostgreSQL", "Azure Data Factory", "GitLab CI/CD", "Elasticsearch", "Java"):
        assert unsupported not in result.resume.headline
        assert unsupported not in serialized
    assert any("headline" in warning for warning in result.warnings)


def test_incomplete_summary_is_replaced_with_complete_source_sentence(tmp_path, profile):
    python = skill("Python")
    store = bank(tmp_path, profile, [python])
    candidate = resume(["Python"], [python.id])
    candidate.professional_summary = (
        "Automates repeatable infrastructure and support workflows with Python and cross-tier."
    )
    result = FactValidator(profile, store).validate(candidate, job("Python support automation"))
    assert result.resume.professional_summary == profile.summary_facts[0]
    assert result.resume.professional_summary.endswith(".")
    assert any("truncated or incomplete" in warning for warning in result.warnings)
