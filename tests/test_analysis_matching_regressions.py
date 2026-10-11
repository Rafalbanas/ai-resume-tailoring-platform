import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, MatchLevel, Recommendation
from app.services.analysis_validator import AnalysisValidator


@pytest.fixture
def real_profile():
    # Synthetic evidence makes these regression checks reproducible in a clean
    # checkout without the candidate's ignored personal files or .env secrets.
    return CandidateProfile.model_validate({
        "personal": {"name": "Audit Candidate"},
        "summary_facts": ["Provides Tier 2 technical support."],
        "skills": {"tools": ["Python", "Linux", "Windows", "Salesforce"]},
        "experience": [{"company": "Example Telecom", "title": "Technical Support Engineer", "facts": [
            "Provides telecommunications support for WAVE PTX partners.",
            "Manages partner support cases in Salesforce.",
        ]}],
        "education": [{"institution": "Example University", "qualification": "MSc in Computer Science", "dates": "2026"}],
        "interests": [{"id": "gravel_cycling", "name": "Gravel cycling"}],
    })


@pytest.fixture
def real_skills_bank():
    return None


def base_analysis(strong=None, partial=None, missing=None) -> JobAnalysis:
    return JobAnalysis(
        company="Motorola Solutions",
        role="Technical Support Specialist",
        strong_matches=strong or [],
        partial_matches=partial or [],
        missing_requirements=missing or [],
        supported_keywords=[],
        unsupported_keywords=[],
        recommendation=Recommendation.APPLY,
        match_level=MatchLevel.HIGH,
        reasoning_summary="Test analysis",
    )


def test_internal_identifiers_never_enter_missing(real_profile, real_skills_bank):
    """Internal IDs from FactCatalog / SkillsBank must never enter missing requirements."""
    corrupted_missing = [
        "skill:7d2c96bf034e",
        "skill:0569868c70b6",
        "skill:experience:ce7f0136d1ac:fact:f988c113d42a",
        "skill:interest:gravel_cycling",
        "skill:education:09528dbef218",
        "skill:project:9483419ecf19:description:623a3b423b88",
        "gravel cycling",
        "KCS (Knowledge Centered Service)",
    ]
    job_text = "Technical Support Specialist with KCS (Knowledge Centered Service) methodology and networking."
    analysis = base_analysis(strong=["Networking"], missing=corrupted_missing)

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    # All internal IDs and candidate interests must be stripped
    for bad_id in [
        "skill:7d2c96bf034e",
        "skill:0569868c70b6",
        "skill:experience:ce7f0136d1ac:fact:f988c113d42a",
        "skill:interest:gravel_cycling",
        "skill:education:09528dbef218",
        "skill:project:9483419ecf19:description:623a3b423b88",
        "gravel cycling",
    ]:
        assert bad_id not in result.missing_requirements
        assert bad_id not in result.strong_matches

    # The real grounded gap KCS is kept
    assert any("kcs" in m.casefold() for m in result.missing_requirements)


def test_fulfilled_education_requirement_matches_msc_computer_science(real_profile, real_skills_bank):
    """MSc in Computer Science (magisterka informatyczna) satisfies Degree in Computer Science."""
    job_text = "Requirements: Education: A Degree or Diploma in Computer Science, Computer Engineering, or equivalent."
    claim = "A Degree or Diploma in Computer Science, Computer Engineering, or equivalent"
    # Even if model incorrectly marks it as missing
    analysis = base_analysis(missing=[claim])

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    # Must be recognized as strong match and not in missing
    assert claim in result.strong_matches
    assert claim not in result.missing_requirements
    assert any("MSc in Computer Science" in ev for ev in result.match_evidence.get(claim, []))


def test_salesforce_proves_crm_experience_and_kcs_evaluated_separately(real_profile, real_skills_bank):
    """Salesforce is proof of CRM experience; KCS is evaluated separately."""
    job_text = "Tools: Experience using CRM systems and working in environments using the KCS methodology."
    claim = "Experience using CRM systems and working in environments using the KCS (Knowledge Centered Service) methodology"
    analysis = base_analysis(missing=[claim])

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    # Salesforce confirms only the CRM part, not the conjunction with KCS.
    req = next(r for r in result.requirements if "kcs" in r.name.casefold())
    assert req.status == "partial"
    assert req.source_quote in job_text
    assert any("salesforce" in ev.casefold() for ev in req.evidence)
    assert result.recommendation != "APPLY"


def test_industry_or_alternatives_satisfied_by_single_branch(real_profile, real_skills_bank):
    """OR alternatives in industry experience: Telecom branch satisfies the requirement."""
    job_text = "Industry Experience: Technical experience in Video Security, Analytics, Access Control, Cloud Software, Telecommunications, or Video Conferencing."
    claim = "Technical experience in Video Security, Analytics, Access Control, Cloud Software, Telecommunications, or Video Conferencing"
    analysis = base_analysis(missing=[claim])

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    # Telecom / Cloud experience in Motorola WAVE PTX satisfies the OR requirement
    assert claim in result.strong_matches
    assert claim not in result.missing_requirements
    assert any("telecommunication" in ev.casefold() for ev in result.match_evidence.get(claim, []))


def test_hallucinated_technologies_not_in_job_rejected(real_profile, real_skills_bank):
    """Technologies absent from the job text (e.g. ONVIF, VMS, CCNA, AWS) must not be added to missing or score."""
    job_text = "Job description for Python Web Developer: requires Python, Django, and PostgreSQL. Team player."
    hallucinated_claims = [
        "Video Standards: ONVIF profile and VMS (Video Management Systems)",
        "IT certifications such as CompTIA A+, CCNA, CCNP",
        "Kubernetes cluster administration",
    ]
    analysis = base_analysis(strong=["Python"], missing=hallucinated_claims)

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    # Hallucinated claims not present in job_text must be discarded
    for claim in hallucinated_claims:
        assert claim not in result.missing_requirements
        assert claim not in result.strong_matches


def test_unreliable_analysis_marked_when_no_valid_requirements(real_profile, real_skills_bank):
    """Corrupted analysis with 0 valid job requirements must be marked as UNRELIABLE and RETRY."""
    job_text = "Some job description text."
    # Analysis with only internal garbage IDs
    analysis = base_analysis(
        strong=[],
        missing=["skill:7d2c96bf034e", "skill:experience:123", "skill:interest:gravel_cycling"],
    )

    result = AnalysisValidator(real_profile, real_skills_bank).validate(analysis, job_text)

    assert result.is_reliable is False
    assert result.match_level == MatchLevel.UNRELIABLE
    assert result.recommendation == Recommendation.RETRY
    assert "Incomplete analysis — review required" in result.reasoning_summary
