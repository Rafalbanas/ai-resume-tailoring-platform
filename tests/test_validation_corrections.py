from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequirement, RequirementComponent
from app.services.analysis_validator import AnalysisValidator
from app.services.fact_catalog import FactCatalog


def profile():
    return CandidateProfile(personal={"name": "Synthetic"}, skills={"network": ["TCP/IP", "DNS", "Linux"]},
        projects=[{"name": "Synthetic web lab", "facts": ["Configured HTTPS certificates using Certbot.",
            "GitHub Actions CI/CD pipeline successfully runs tests and deploys the application."]}])


def fact_id(p, value):
    return next(e.source_id for e in FactCatalog(p).prompt_entries if value in e.text)


def validate(p, text, rows):
    analysis = JobAnalysis(company="Synthetic", role="Engineer", strong_matches=[], partial_matches=[],
        missing_requirements=[], recommendation="REVIEW", match_level="LIMITED", requirements=rows)
    return AnalysisValidator(p).validate(analysis, text, semantic=True)


def networking(p, *, invalid=False):
    return JobRequirement(name="Networking (TCP/IP, DNS, HTTP(s))",
        source_quote="Podstawowa orientacja w zagadnieniach sieciowych (TCP/IP, DNS, HTTP(s)).",
        operator="all", status="strong", reason="Each named protocol has separate documented evidence.",
        source_fact_ids=[fact_id(p, "TCP/IP"), fact_id(p, "DNS"), fact_id(p, "Configured HTTPS")],
        components=[RequirementComponent(name=term, status="strong", reason="Documented evidence.",
            source_fact_ids=["nonexistent:fact" if invalid and term == "HTTP(s)" else fact_id(p, text)])
            for term, text in [("TCP/IP", "TCP/IP"), ("DNS", "DNS"), ("HTTP(s)", "Configured HTTPS")]])


def test_compound_networking_keeps_https_evidence_without_stale_issue():
    p = profile()
    row = networking(p)
    result = validate(p, "REQUIREMENTS\n" + row.source_quote, [row])
    assert result.is_reliable
    assert not result.evidence_issues
    assert result.requirements[0].status == "strong"
    assert fact_id(p, "Configured HTTPS") in result.requirements[0].source_fact_ids
    second = AnalysisValidator(p).validate(result, "REQUIREMENTS\n" + row.source_quote)
    assert second.is_reliable and not second.evidence_issues


def test_invalid_network_component_still_blocks_confirmation():
    p = profile()
    row = networking(p, invalid=True)
    result = validate(p, "REQUIREMENTS\n" + row.source_quote, [row])
    assert not result.is_reliable
    assert result.evidence_issues
    assert result.requirements[0].status != "strong"
    assert "nonexistent:fact" not in result.requirements[0].source_fact_ids


def test_compound_networking_does_not_infer_advanced_proficiency():
    p = profile()
    row = networking(p)
    row.name = "Advanced networking (TCP/IP, DNS, HTTP(s))"
    result = validate(p, "REQUIREMENTS\n" + row.source_quote, [row])
    assert not result.is_reliable
    assert result.requirements[0].status != "strong"
    assert result.evidence_issues


def test_ci_cd_examples_do_not_reclassify_requirement_as_ansible():
    p = profile()
    quote = "Wiedza o CI/CD (Ansible, GitLab lub podobne)."
    row = JobRequirement(name="CI/CD (Ansible, GitLab or similar)", source_quote=quote, priority="preferred",
        status="strong", source_fact_ids=[fact_id(p, "GitHub Actions")], reason="Documented successful CI/CD execution.")
    result = validate(p, "NICE TO HAVE\n" + quote, [row])
    assert result.is_reliable
    assert not result.evidence_issues
    assert result.requirements[0].status == "strong"
    assert fact_id(p, "GitHub Actions") in result.requirements[0].source_fact_ids


def test_corrected_responsibility_stays_auditable_but_does_not_block_report():
    p = profile()
    duty = "Wspieramy zespoły deweloperskie we wdrażaniu i utrzymaniu usług DNS."
    requirement = JobRequirement(name="Linux", source_quote="Linux", status="strong",
        source_fact_ids=[fact_id(p, "Linux")], reason="Declared Linux knowledge.")
    misplaced = JobRequirement(name="Telco DNS", source_quote=duty, status="missing", reason="Unconfirmed duty scope.")
    result = validate(p, "RESPONSIBILITIES\n" + duty + "\nREQUIREMENTS\nLinux", [requirement, misplaced])
    assert result.is_reliable
    assert not result.classification_issues
    assert result.validation_corrections
    assert all(r.name != "Telco DNS" for r in result.requirements)
    assert any(r["source_quote"] == duty for r in result.responsibilities)
    again = AnalysisValidator(p).validate(result, "RESPONSIBILITIES\n" + duty + "\nREQUIREMENTS\nLinux")
    assert again.is_reliable
    assert again.validation_corrections == result.validation_corrections
