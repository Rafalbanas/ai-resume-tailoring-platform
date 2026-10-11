import json
from pathlib import Path

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

    assert result.resume.headline == "Support Engineer | Python | Linux"
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
    assert any("source sentences" in warning for warning in result.warnings)


# ---------------------------------------------------------------------------
# Skills Bank & Role Selection Regression Tests
# ---------------------------------------------------------------------------


def test_all_verified_skills_require_evidence():
    with pytest.raises(ValidationError, match="requires evidence"):
        VerifiedSkill(
            id="skill_custom",
            name="Custom Skill",
            category="Backend / Python",
            level="hands_on",
            verified=True,
            allowed_in_cv=True,
            evidence=[],
        )


def test_synthetic_bank_unique_ids_and_names(tmp_path, profile):
    s1 = skill("FastAPI", aliases=["fast-api"])
    s2 = skill("Pydantic")
    store = bank(tmp_path, profile, [s1, s2])
    assert store.get(s1.id) == s1
    assert store.find("fast-api") == s1
    assert store.find("Pydantic") == s2


def test_learning_and_disabled_skills_never_enter_cv_synthetic(tmp_path, profile):
    postgres = skill("PostgreSQL", level="learning", verified=False, allowed=False)
    docker_disabled = skill("Docker", enabled=False)
    python = skill("Python")
    store = bank(tmp_path, profile, [postgres, docker_disabled, python])

    candidate = resume(["PostgreSQL", "Docker", "Python"], [postgres.id, docker_disabled.id, python.id])
    result = FactValidator(profile, store).validate(candidate, job("PostgreSQL, Docker, and Python developer"))
    assert "PostgreSQL" not in result.resume.core_skills
    assert "Docker" not in result.resume.core_skills
    assert any("Python" in s for s in result.resume.core_skills)


def test_github_derived_skills_pass_fact_validator_synthetic(tmp_path, profile):
    fastapi = skill("FastAPI", category="Backend / Python")
    xgboost = skill("XGBoost", category="Data / ML")
    store = bank(tmp_path, profile, [fastapi, xgboost])

    candidate = resume([], [fastapi.id, xgboost.id])
    result = FactValidator(profile, store).validate(candidate, job("FastAPI backend and XGBoost predictive models"))
    assert any("FastAPI" in s for s in result.resume.core_skills)
    assert any("XGBoost" in s for s in result.resume.core_skills)
    assert not any("Unsupported AI fact" in w for w in result.warnings)


def test_support_role_not_dominated_by_backend_or_ml(tmp_path, profile):
    skills = [
        skill("Windows", priority=9, category="IT Support"),
        skill("Active Directory", aliases=["AD"], priority=9, category="IT Support"),
        skill("Troubleshooting", priority=8, category="IT Support"),
        skill("Jira", priority=8, category="IT Support"),
        skill("XGBoost", priority=7, category="Data / ML"),
        skill("SHAP", priority=7, category="Data / ML"),
        skill("FastALPR", priority=6, category="Computer Vision"),
    ]
    store = bank(tmp_path, profile, skills)
    selected = store.select_for_job(
        [],
        "Technical Support Specialist Windows Active Directory Jira troubleshooting",
        maximum=4,
    )
    selected_names = [s.name for s in selected]
    assert "XGBoost" not in selected_names
    assert "SHAP" not in selected_names
    assert "FastALPR" not in selected_names
    assert any(s in selected_names for s in ["Windows", "Active Directory", "Troubleshooting", "Jira"])


def test_platform_role_prioritises_infrastructure_synthetic(tmp_path, profile):
    skills = [
        skill("Linux", priority=9, category="Infrastructure"),
        skill("Docker", priority=9, category="Infrastructure"),
        skill("systemd", priority=8, category="Infrastructure"),
        skill("Nginx", priority=8, category="Infrastructure"),
        skill("Python", priority=8, category="Engineering"),
        skill("Customer Service", priority=5, category="Support"),
    ]
    store = bank(tmp_path, profile, skills)
    selected = store.select_for_job(
        [],
        "Platform Engineer Linux Docker systemd Nginx Python automation",
        maximum=5,
    )
    selected_names = [s.name for s in selected]
    assert "Linux" in selected_names
    assert "Docker" in selected_names
    assert "systemd" in selected_names
    assert "Nginx" in selected_names
    assert "Python" in selected_names
    assert "Customer Service" not in selected_names


def test_ai_python_role_selects_expected_stack_synthetic(tmp_path, profile):
    skills = [
        skill("FastAPI", priority=9, category="Backend / Python"),
        skill("Pydantic", priority=9, category="Backend / Python"),
        skill("Ollama", priority=9, category="AI / ML"),
        skill("REST API integration", priority=8, category="Backend / Python"),
        skill("Windows Server", priority=5, category="IT Support"),
    ]
    store = bank(tmp_path, profile, skills)
    selected = store.select_for_job(
        [],
        "Python AI Developer FastAPI Pydantic Ollama REST API integration",
        maximum=4,
    )
    selected_names = [s.name for s in selected]
    assert "FastAPI" in selected_names
    assert "Pydantic" in selected_names
    assert "Ollama" in selected_names
    assert "REST API integration" in selected_names
    assert "Windows Server" not in selected_names


def test_data_ml_role_selects_expected_stack_synthetic(tmp_path, profile):
    skills = [
        skill("XGBoost", priority=9, category="Data / ML"),
        skill("scikit-learn", priority=9, category="Data / ML"),
        skill("SHAP", priority=8, category="Data / ML"),
        skill("pandas", priority=8, category="Data / ML"),
        skill("NumPy", priority=8, category="Data / ML"),
        skill("Active Directory", priority=5, category="IT Support"),
    ]
    store = bank(tmp_path, profile, skills)
    selected = store.select_for_job(
        [],
        "Data Scientist Machine Learning XGBoost scikit-learn SHAP pandas NumPy",
        maximum=5,
    )
    selected_names = [s.name for s in selected]
    assert "XGBoost" in selected_names
    assert "scikit-learn" in selected_names
    assert "SHAP" in selected_names
    assert "pandas" in selected_names
    assert "NumPy" in selected_names
    assert "Active Directory" not in selected_names


# ---------------------------------------------------------------------------
# Production Skills Bank Validation (runs when data/skills.json is present)
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
SKILLS_JSON_PATH = DATA_DIR / "skills.json"
MASTER_PROFILE_PATH = DATA_DIR / "master_profile.json"


@pytest.mark.skipif(not SKILLS_JSON_PATH.exists(), reason="data/skills.json not present")
def test_production_skills_bank_integrity():
    from app.models.candidate import CandidateProfile

    doc = SkillsDocument.model_validate_json(SKILLS_JSON_PATH.read_text(encoding="utf-8"))

    # 1. All verified skills have >= 1 evidence
    for s in doc.skills:
        if s.verified:
            assert len(s.evidence) >= 1, f"Skill {s.id} ({s.name}) is verified but has no evidence"
            assert s.allowed_in_cv is True, f"Verified skill {s.id} should be allowed in CV"
        else:
            assert s.allowed_in_cv is False, f"Unverified skill {s.id} must not be allowed in CV"

    # 2. All skill IDs and names are unique
    ids = [s.id for s in doc.skills]
    names = [s.name.casefold() for s in doc.skills]
    assert len(ids) == len(set(ids)), f"Duplicate skill IDs found: {[x for x in ids if ids.count(x) > 1]}"
    assert len(names) == len(set(names)), f"Duplicate skill names found: {[x for x in names if names.count(x) > 1]}"

    # 3. Aliases resolve properly
    profile_data = (
        CandidateProfile.model_validate_json(MASTER_PROFILE_PATH.read_text(encoding="utf-8"))
        if MASTER_PROFILE_PATH.exists()
        else None
    )
    if profile_data:
        prod_bank = SkillsBank(SKILLS_JSON_PATH, profile_data)
        for s in doc.skills:
            assert prod_bank.find(s.name) == s, f"Skill {s.name} did not resolve by name"
            for alias in s.aliases:
                found = prod_bank.find(alias)
                assert found is not None, f"Alias {alias} for {s.name} did not resolve"


@pytest.mark.skipif(
    not (SKILLS_JSON_PATH.exists() and MASTER_PROFILE_PATH.exists()),
    reason="Production files not present",
)
def test_production_skills_bank_role_selection_and_evidence():
    from app.models.candidate import CandidateProfile

    profile = CandidateProfile.model_validate_json(MASTER_PROFILE_PATH.read_text(encoding="utf-8"))
    prod_bank = SkillsBank(SKILLS_JSON_PATH, profile)

    # Support CV selection is not dominated by backend/ML tools
    support_skills = [
        s.name
        for s in prod_bank.select_for_job(
            [],
            "IT Support Specialist Technical Support Jira Active Directory Windows hardware troubleshooting ticketing".ljust(
                30, "."
            ),
            maximum=8,
        )
    ]
    ml_tools = {"XGBoost", "Ultralytics / YOLO", "FastALPR", "SHAP / Model Explainability", "scikit-learn"}
    assert not any(tool in support_skills for tool in ml_tools), f"Support CV contains ML tools: {support_skills}"
    assert any(s in support_skills for s in ["Active Directory", "Windows", "Jira", "Troubleshooting"])

    # Platform CV prioritises infrastructure skills
    platform_skills = [
        s.name
        for s in prod_bank.select_for_job(
            [],
            "Platform Engineer Linux systemd Docker Nginx Python reverse proxy Bash automation CI/CD deployment".ljust(
                30, "."
            ),
            maximum=8,
        )
    ]
    assert any(s in platform_skills for s in ["Linux", "Docker", "systemd", "Nginx", "Python"])

    # AI / Python CV selects FastAPI, Pydantic, Ollama, API integration
    ai_skills = [
        s.name
        for s in prod_bank.select_for_job(
            [],
            "Python Backend AI Developer FastAPI Pydantic Ollama REST API integration Local LLMs Prompt Engineering".ljust(
                30, "."
            ),
            maximum=8,
        )
    ]
    assert any(s in ai_skills for s in ["FastAPI", "Pydantic", "Ollama", "REST API integration"])

    # Data / ML CV selects XGBoost, scikit-learn, SHAP, pandas
    ml_skills = [
        s.name
        for s in prod_bank.select_for_job(
            [],
            "Machine Learning Engineer Data Scientist pandas NumPy scikit-learn XGBoost SHAP Regression Feature Engineering".ljust(
                30, "."
            ),
            maximum=8,
        )
    ]
    assert any(s in ml_skills for s in ["XGBoost", "scikit-learn", "SHAP / Model Explainability", "pandas"])

    # FactValidator blocks PostgreSQL (unverified/learning) and allows verified skills
    validator = FactValidator(profile, prod_bank)
    fastapi = prod_bank.find("FastAPI")
    xgboost = prod_bank.find("XGBoost")
    postgres = prod_bank.find("PostgreSQL")
    assert postgres.level == "learning" and not postgres.verified

    cand = resume(["PostgreSQL", "FastAPI", "XGBoost"], [postgres.id, fastapi.id, xgboost.id])
    res = validator.validate(
        cand,
        JobRequest(
            company="Tech Corp",
            role="Python & ML Developer",
            job_description="Requires FastAPI backend development, XGBoost model training, and PostgreSQL experience.",
        ),
    )
    assert "PostgreSQL" not in res.resume.core_skills
    assert any("FastAPI" in s for s in res.resume.core_skills)
    assert any("XGBoost" in s for s in res.resume.core_skills)
    assert any("PostgreSQL" in w for w in res.warnings)

