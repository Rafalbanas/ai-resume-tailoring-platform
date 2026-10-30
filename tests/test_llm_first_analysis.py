from datetime import date
from pathlib import Path

import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest, JobRequirement, RequirementComponent
from app.services.ai_provider import build_compact_analysis_payload
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher
from app.services.fact_catalog import FactCatalog
from app.services.job_sections import extract_sections
from tests.test_evidence_matching import candidate
from tests.test_evidence_matching import contextual_profile as source_profile


@pytest.fixture
def contextual_profile():
    return source_profile.__wrapped__()


def interpret(profile, text, rows):
    v = AnalysisValidator(profile)
    v.matcher = EvidenceMatcher(v.catalog, as_of=date(2026, 10, 12))
    draft = candidate()
    draft.requirements = rows
    return v.validate(draft, text, semantic=True)


def ids(profile, term):
    return [
        e.source_id
        for e in FactCatalog(profile).prompt_entries
        if term.casefold() in e.text.casefold() and e.kind != "skill"
    ]


def test_semantic_paraphrase_and_unfamiliar_heading_survive_validation():
    p = CandidateProfile.model_validate(
        {
            "personal": {"name": "Example"},
            "projects": [{"name": "Mesh lab", "facts": ["Implemented PhotonStack connectors between mesh services."]}],
        }
    )
    text = "JOB DESCRIPTION\n## How you can contribute\nBuild connectors between mesh services."
    req = JobRequirement(
        name="Integration of service mesh connectors",
        source_quote="Build connectors between mesh services.",
        status="strong",
        source_fact_ids=ids(p, "PhotonStack"),
        reason="The project implements the same connector capability with documented PhotonStack use.",
    )
    result = interpret(p, text, [req])
    assert result.is_reliable and result.requirements[0].status == "strong"
    assert result.requirements[0].name == req.name and result.requirements[0].reason == req.reason
    assert result.requirements[0].interpretation_origin == "llm"
    assert result.analysis_method == "llm_validated"
    assert result.source_context[0]["category"] == "unknown"
    assert AnalysisValidator(p).validate(result, text).requirements[0].status == "strong"


def test_model_may_recognize_solid_level_from_real_practice(contextual_profile):
    text = "Requirements\nSolid knowledge of incident investigation"
    req = JobRequirement(
        name="Solid incident investigation knowledge",
        source_quote=text.splitlines()[1],
        status="strong",
        source_fact_ids=ids(contextual_profile, "root causes"),
        reason="Employment documents incident investigation and root-cause analysis; this supports the requested working scope, without claiming expert administration.",
    )
    assert interpret(contextual_profile, text, [req]).requirements[0].status == "strong"


def test_invalid_fact_ids_and_unjustified_gap_do_not_confirm(profile):
    text = "Requirements\nPython automation\nOracle administration"
    rows = [
        JobRequirement(
            name="Python automation",
            source_quote="Python automation",
            status="strong",
            source_fact_ids=["invented"],
            reason="Incorrect ID",
        ),
        JobRequirement(
            name="Oracle administration",
            source_quote="Oracle administration",
            status="absent",
            reason="No mention of Oracle",
        ),
    ]
    result = interpret(profile, text, rows)
    assert [r.status for r in result.requirements] == ["missing", "missing"]
    assert not result.requirement_counts["confirmed_absence"]


def test_and_components_prevent_json_api_overconfirmation(contextual_profile):
    text = "Requirements\nKnowledge of Elasticsearch, GraphQL, JSON and REST API"
    components = [
        RequirementComponent(name="Elasticsearch", status="missing", reason="No documented use."),
        RequirementComponent(name="GraphQL", status="missing", reason="No documented use."),
        RequirementComponent(
            name="JSON", status="strong", source_fact_ids=ids(contextual_profile, "HTTPX"), reason="Project uses JSON."
        ),
        RequirementComponent(
            name="REST API",
            status="strong",
            source_fact_ids=ids(contextual_profile, "REST API integration"),
            reason="Project implements REST integration.",
        ),
    ]
    row = JobRequirement(
        name=text.splitlines()[1],
        source_quote=text.splitlines()[1],
        operator="all",
        components=components,
        status="strong",
        reason="Each technology is assessed separately.",
    )
    req = interpret(contextual_profile, text, [row]).requirements[0]
    assert req.status == "partial" and len(req.components) == 4
    row.components = []
    row.source_fact_ids = ids(contextual_profile, "HTTPX")
    assert interpret(contextual_profile, text, [row]).requirements[0].status == "partial"
    fallback = AnalysisValidator(contextual_profile).validate(candidate(), text).requirements[0]
    assert fallback.status == "partial" and len(fallback.components) == 4


def test_or_components_require_one_documented_alternative(contextual_profile):
    text = "Requirements\nUse Python or TypeScript for automation"
    row = JobRequirement(
        name=text.splitlines()[1],
        source_quote=text.splitlines()[1],
        operator="any",
        status="missing",
        reason="One language suffices.",
        components=[
            RequirementComponent(
                name="Python",
                status="strong",
                source_fact_ids=ids(contextual_profile, "Automated"),
                reason="Automation fact.",
            ),
            RequirementComponent(name="TypeScript", status="missing", reason="Unconfirmed."),
        ],
    )
    req = interpret(contextual_profile, text, [row]).requirements[0]
    assert req.status == "strong" and req.components[1].status == "missing"


def test_b2_plus_and_dated_tenure_are_objective_checks(contextual_profile):
    quote = "English B2+ communication"
    row = JobRequirement(
        name="English communication",
        source_quote=quote,
        required_level="B2+",
        status="strong",
        source_fact_ids=ids(contextual_profile, "English"),
        reason="Candidate uses English.",
    )
    assert interpret(contextual_profile, "Requirements\n" + quote, [row]).requirements[0].status == "partial"
    row = JobRequirement(
        name="3+ years of systems or similar role",
        source_quote="3+ years of systems or similar role",
        required_years=1,
        observed_years=8,
        status="strong",
        source_fact_ids=ids(contextual_profile, "operational queries") + ids(contextual_profile, "Automated"),
        reason="These employment duties are relevant.",
    )
    req = interpret(contextual_profile, "Requirements\n" + row.source_quote, [row]).requirements[0]
    assert req.required_years == 3 and req.observed_years == 2.51 and req.status == "partial"


def test_git_ci_and_telecom_are_not_downgraded_by_evidence_location():
    p = CandidateProfile.model_validate(
        {
            "personal": {"name": "Example"},
            "projects": [
                {
                    "name": "Public repository",
                    "facts": ["Uses Git branches and commits; GitHub Actions runs CI tests and lint checks."],
                }
            ],
            "experience": [
                {
                    "company": "Example Telecom",
                    "title": "Support",
                    "start": "2024-01",
                    "end": "Present",
                    "facts": ["Supports WAVE PTX telecommunications connectivity and technical incidents."],
                }
            ],
        }
    )
    rows = [
        JobRequirement(
            name="Git and CI workflows",
            source_quote="Git and CI workflows",
            status="strong",
            source_fact_ids=ids(p, "Git branches"),
            reason="Repository documents version control and CI workflows.",
        ),
        JobRequirement(
            name="Telecommunications experience",
            source_quote="Telecommunications experience",
            status="strong",
            source_fact_ids=ids(p, "WAVE PTX"),
            reason="Employment documents telecom connectivity support.",
        ),
        JobRequirement(
            name="Operator business processes",
            source_quote="Operator business processes",
            status="partial",
            source_fact_ids=ids(p, "WAVE PTX"),
            reason="Technical telecom support does not establish operator business processes.",
        ),
    ]
    result = interpret(p, "Requirements\n" + "\n".join(r.source_quote for r in rows), rows)
    assert [r.status for r in result.requirements] == ["strong", "strong", "partial"]
    assert result.requirements[0].evidence_sources[0]["type"] == "project"


def test_full_input_keeps_benefits_recruitment_and_source_catalog(profile):
    job = JobRequest.model_validate_json(Path("tests/fixtures/saved_jobs/veeva.json").read_text())
    payload = build_compact_analysis_payload(job, profile)
    assert payload["job"]["job_description"] == job.job_description
    assert all(
        text in payload["job"]["job_description"]
        for text in ["MultiSport", "LuxMed", "personality assessment", "Compensation"]
    )
    assert payload["source_catalog"][0]["source_id"]
    assert payload["job"]["job_url"] == str(job.job_url)


@pytest.mark.parametrize("name", ["veeva", "comarch_telco", "comarch_sql", "winged", "onerail", "rtb"])
def test_saved_offers_sections_and_quality_are_offline(name, contextual_profile):
    job = JobRequest.model_validate_json(Path(f"tests/fixtures/saved_jobs/{name}.json").read_text())
    result = AnalysisValidator(contextual_profile).validate(candidate(), job.job_description)
    if name == "veeva":
        assert result.requirement_counts["mandatory"] == 6
        assert result.requirement_counts["preferred"] == 2
        assert not any(
            t in r.name
            for r in result.requirements
            for t in ["MultiSport", "LuxMed", "Compensation", "Interview", "assessment", "contract"]
        )
        assert {"benefits", "employment", "recruitment"} <= {c["category"] for c in result.source_context}
    if name.startswith("comarch"):
        assert result.requirement_counts["mandatory"] >= 8
        assert len(result.responsibilities) == 6
        assert not any("Allianz" in r.name or "Multisport" in r.name for r in result.requirements)
        # Source coverage alone cannot validate unresolved slash/combined scopes.
        assert not result.is_reliable
        if name == "comarch_telco":
            assert not result.completeness_issues
            assert result.classification_issues
    if name == "winged":
        assert result.requirement_counts["mandatory"] == 8
        assert any(r.priority == "nice_to_have" for r in result.requirements)
    if name == "onerail":
        assert any(r.priority == "preferred" and r.operator == "any" for r in result.requirements)
    if name == "rtb":
        assert result.match_level == "LIMITED" and result.requirement_counts["mandatory"] == 0
        assert len(result.responsibilities) == 5


def test_public_sources_are_distinct_not_a_cached_cross_offer():
    jobs = [
        JobRequest.model_validate_json(Path(f"tests/fixtures/saved_jobs/comarch_{name}.json").read_text())
        for name in ["telco", "sql"]
    ]
    assert jobs[0].job_url != jobs[1].job_url
    assert jobs[0].job_description != jobs[1].job_description
    assert "PL/SQL)" in jobs[0].job_description
    assert "PL/SQLDobra" in jobs[1].job_description
    assert extract_sections(jobs[0].job_description)[0]


def test_target_title_is_context_and_literal_and_cannot_become_or(contextual_profile):
    title = "Support"
    quote = "Experience handling XML, CSV, Google Sheets, and JSON files"
    rows = [
        JobRequirement(
            name="Tier 2 Support Engineer",
            source_quote=title,
            status="strong",
            source_fact_ids=ids(contextual_profile, "technical support"),
            reason="Title match.",
        ),
        JobRequirement(
            name=quote,
            source_quote=quote,
            operator="any",
            status="strong",
            reason="JSON is documented; other formats are not.",
            components=[
                RequirementComponent(
                    name="JSON",
                    status="strong",
                    source_fact_ids=ids(contextual_profile, "HTTPX"),
                    reason="JSON integration.",
                ),
                RequirementComponent(name="XML", status="missing", reason="Unconfirmed."),
                RequirementComponent(name="CSV", status="missing", reason="Unconfirmed."),
                RequirementComponent(name="Google Sheets", status="missing", reason="Unconfirmed."),
            ],
        ),
    ]
    result = interpret(contextual_profile, title + "\nPreferred qualifications\n" + quote, rows)
    assert len(result.requirements) == 1
    assert result.requirements[0].operator == "all"
    assert result.requirements[0].status == "partial"
    assert result.requirements[0].interpretation_uncertain


def test_source_recovery_is_literal_and_does_not_accept_candidate_quotes(profile):
    from app.services.semantic_requirements import resolve_source_quotes

    assert resolve_source_quotes("Basic SQL knowledge.", "Requirements\nBasic SQL knowledge;") == [
        "Basic SQL knowledge"
    ]
    assert resolve_source_quotes("Uses Python for troubleshooting.", "Requirements\nBasic SQL knowledge;") == []


def test_model_cannot_lower_explicit_source_level_or_years(contextual_profile):
    row = JobRequirement(
        name="English B2",
        source_quote="English B2+",
        required_level="B2",
        status="strong",
        source_fact_ids=ids(contextual_profile, "English"),
        reason="Incorrectly simplified level.",
    )
    result = interpret(contextual_profile, "Requirements\nEnglish B2+", [row])
    assert result.requirements[0].required_level.upper() == "B2+"
    assert result.requirements[0].status == "partial"
    row = JobRequirement(
        name="2 years of support experience",
        source_quote="3 years of support experience",
        required_years=2,
        status="strong",
        source_fact_ids=ids(contextual_profile, "operational queries") + ids(contextual_profile, "Automated"),
        reason="Relevant employment.",
    )
    req = interpret(contextual_profile, "Requirements\n" + row.source_quote, [row]).requirements[0]
    assert req.required_years == 3 and req.status == "partial"


def test_known_language_does_not_overwrite_partial_compound_scope(contextual_profile):
    quote = "English B2 and advanced SQL administration"
    row = JobRequirement(
        name=quote,
        source_quote=quote,
        status="partial",
        source_fact_ids=ids(contextual_profile, "English") + ids(contextual_profile, "operational queries"),
        reason="B2 is documented; advanced SQL administration is unconfirmed.",
    )
    assert interpret(contextual_profile, "Requirements\n" + quote, [row]).requirements[0].status == "partial"
    row = JobRequirement(
        name="English communication",
        source_quote="Fluent English",
        required_level="B2",
        status="strong",
        source_fact_ids=ids(contextual_profile, "English"),
        reason="Incorrectly reduced the required fluency.",
    )
    assert interpret(contextual_profile, "Requirements\nFluent English", [row]).requirements[0].status == "partial"


def test_comma_list_keeps_every_scope_in_legacy_review(contextual_profile):
    text = "Preferred qualifications\nUnderstanding of Java, SSO, SQL, HTML"
    result = AnalysisValidator(contextual_profile).validate(candidate(), text)
    assert result.requirements[0].status == "partial"
    assert [c.name for c in result.requirements[0].components] == ["Java", "SSO", "SQL", "HTML"]


def test_explicit_optional_priority_is_checked_without_weakening_mandatory_clause(contextual_profile):
    text = "Requirements\nExperience with virtual desktops (big plus);\nRelease processes and DLP (optional);\nFamiliarity with PowerShell scripting and automation; knowledge of Python is considered an advantage;"
    rows = [
        JobRequirement(
            name="Virtual desktops",
            source_quote="Experience with virtual desktops (big plus);",
            priority="mandatory",
            status="missing",
            reason="Unconfirmed.",
        ),
        JobRequirement(
            name="Release processes and DLP",
            source_quote="Release processes and DLP (optional);",
            priority="mandatory",
            status="missing",
            reason="Unconfirmed.",
        ),
        JobRequirement(
            name="PowerShell scripting and automation",
            source_quote=text.splitlines()[-1],
            priority="mandatory",
            status="strong",
            source_fact_ids=ids(contextual_profile, "Automated"),
            reason="Employment documents PowerShell automation.",
        ),
    ]
    result = interpret(contextual_profile, text, rows)
    assert [r.priority for r in result.requirements[:3]] == ["preferred", "nice_to_have", "mandatory"]
    assert not result.requirements[2].interpretation_uncertain
