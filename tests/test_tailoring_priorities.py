"""Offer-specific emphasis changes source selection, never the candidate facts."""

from pathlib import Path
from zipfile import ZipFile

import pytest
from pypdf import PdfReader

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis, JobRequest, JobRequirement
from app.models.resume import TailoredResume
from app.services.ai_provider import build_compact_tailor_payload
from app.services.docx_generator import generate_docx
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator


def candidate():
    return CandidateProfile.model_validate(
        {
            "personal": {
                "name": "Alex Example",
                "email": "alex@example.com",
                "linkedin": "https://www.linkedin.com/in/alex-example",
            },
            "summary_facts": ["Uses English at B2 level in professional communication."],
            "skills": {
                "technical": ["Linux", "Python", "Docker (basic)", "Network Troubleshooting"],
                "languages": ["English B2"],
            },
            "experience": [
                {
                    "company": "Example Ltd",
                    "title": "Support Engineer",
                    "start": "2023",
                    "end": "Present",
                    "facts": [
                        "Investigates network incidents and escalates technical tickets.",
                        "Automates Linux service checks with Python scripts.",
                    ],
                }
            ],
            "projects": [
                {
                    "name": "Service lab",
                    "description": "A personal infrastructure lab.",
                    "technologies": ["Linux", "Docker (basic)"],
                    "facts": [
                        "Runs Linux services in Docker containers.",
                        "A CI workflow file exists; production deployment is planned.",
                    ],
                    "url": "https://github.com/example/service-lab?tracking=" + "x" * 200,
                },
                {
                    "name": "Support notes",
                    "description": "An operational support project.",
                    "technologies": ["Python"],
                    "facts": ["Documents network incident investigation and ticket escalation."],
                },
            ],
        }
    )


def scenario(profile, direction):
    catalog = FactCatalog(profile)
    if direction == "infrastructure":
        job = JobRequest(
            company="A",
            role="Junior Infrastructure Engineer",
            job_description="Requirements\nLinux services\nDocker containers\nPython automation\nResponsibilities\nMaintain infrastructure\nBenefits\nCustomer support for insurance claims",
        )
        preferred = [profile.experience[0].facts[1], profile.projects[0].facts[0]]
    else:
        job = JobRequest(
            company="B",
            role="Technical Support Engineer",
            job_description="Requirements\nNetwork incident investigation\nTechnical ticket escalation\nResponsibilities\nDocument support procedures",
        )
        preferred = [profile.experience[0].facts[0], profile.projects[1].facts[0]]
    entries = [next(e for e in catalog.prompt_entries if e.text == text) for text in preferred]
    analysis = JobAnalysis(
        company=job.company,
        role=job.role,
        strong_matches=[],
        partial_matches=[],
        missing_requirements=[],
        recommendation="REVIEW",
        match_level="LOW",
        requirements=[
            JobRequirement(
                name=entry.text,
                source_quote=entry.text,
                priority="mandatory",
                status="strong",
                source_fact_ids=[entry.source_id],
                reason="Attested source",
            )
            for entry in entries
        ],
    )
    draft = TailoredResume(
        headline="Support Engineer | Linux",
        professional_summary="Unverified advanced engineering experience.",
        core_skills=["Linux", "Python", "Docker (basic)", "English C1", "Kubernetes"],
        experience=[],
        projects=[],
    )
    return job, analysis, FactValidator(profile, analysis=analysis).validate(draft, job).resume


def test_same_profile_different_offers_keep_facts_but_change_emphasis():
    profile = candidate()
    original = profile.model_dump()
    _, _, infrastructure = scenario(profile, "infrastructure")
    _, _, support = scenario(profile, "support")
    assert infrastructure.experience[0].bullets[0].source_fact_ids != support.experience[0].bullets[0].source_fact_ids
    assert infrastructure.projects[0].name == "Service lab"
    assert support.projects[0].name == "Support notes"
    opener, _, details = infrastructure.professional_summary.partition(". ")
    assert opener == "Support Engineer at Example Ltd"
    assert "Linux" in details.split(".")[0]
    assert profile.model_dump() == original
    catalog = FactCatalog(profile)
    for resume in [infrastructure, support]:
        assert resume.experience[0].company == profile.experience[0].company
        assert resume.experience[0].title == profile.experience[0].title
        assert "Kubernetes" not in resume.model_dump_json() and "English C1" not in resume.model_dump_json()
        assert "Docker (basic)" in resume.core_skills
        for exp in resume.experience:
            for bullet in exp.bullets:
                assert catalog.supports_paraphrase(bullet.text, bullet.source_fact_ids)
        assert (
            "production deployment is planned"
            in next(p for p in resume.projects if p.name == "Service lab").description
            or "production" not in next(p for p in resume.projects if p.name == "Service lab").description
        )


def test_tailor_payload_preserves_all_requirements_and_evidence():
    profile = candidate()
    job, analysis, _ = scenario(profile, "infrastructure")
    analysis.requirements *= 7
    payload = build_compact_tailor_payload(job, profile, analysis)
    assert len(payload["analysis_summary"]["requirements_with_evidence"]) == 14
    assert payload["analysis_summary"]["requirements_with_evidence"][0]["source_fact_ids"]
    assert payload["analysis_summary"]["requirements_with_evidence"][0]["priority"] == "mandatory"
    assert payload["job_description"] == job.job_description


def test_headline_accepts_verified_direction_but_rejects_expertise():
    profile = candidate()
    job, _, draft = scenario(profile, "infrastructure")
    assert draft.headline == "Support Engineer | Linux"
    draft.headline = "DevOps Engineer | Docker expertise"
    repaired = FactValidator(profile).validate(draft, job).resume
    assert repaired.headline == "Support Engineer"
    draft.headline = "Support Engineer | Docker expertise"
    assert "expertise" not in FactValidator(profile).validate(draft, job).resume.headline


@pytest.mark.parametrize("layout", ["modern_sidebar", "ats_classic"])
def test_both_scenarios_export_with_visible_project_links(tmp_path, layout):
    profile = candidate()
    for direction in ["infrastructure", "support"]:
        _, _, resume = scenario(profile, direction)
        path = tmp_path / direction
        path.mkdir()
        PDFGenerator(Path("templates"), Path("static"), data_dir=path).generate(
            resume, profile, path / "cv.pdf", template_name=layout
        )
        generate_docx(resume, profile, path / "cv.docx")
        reader = PdfReader(path / "cv.pdf")
        text = " ".join(p.extract_text() for p in reader.pages)
        assert "Support Engineer" in text and "example/service-lab" in text
        targets = {
            str(a.get_object().get("/A", {}).get("/URI", "")) for page in reader.pages for a in page.get("/Annots", [])
        }
        assert profile.projects[0].url in targets
        with ZipFile(path / "cv.docx") as z:
            xml = z.read("word/document.xml").decode()
            rels = z.read("word/_rels/document.xml.rels").decode()
            assert "github.com/example/service-lab" in xml
            assert "tracking=" not in xml and "tracking=" in rels


def test_incomplete_profile_and_empty_projects_remain_safe():
    profile = candidate()
    profile.projects = []
    profile.experience = []
    profile.summary_facts = []
    job = JobRequest(company="A", role="Engineer", job_description="Requirements\nKubernetes expertise")
    draft = TailoredResume(
        headline="Senior Engineer", professional_summary="Kubernetes expert.", core_skills=["Kubernetes"], experience=[]
    )
    result = FactValidator(profile).validate(draft, job).resume
    assert result.headline == "Professional Profile"
    assert not result.projects and not result.experience
    assert set(result.core_skills) == set(profile.skills["technical"])
    assert "Kubernetes" not in result.core_skills
    assert "expert" not in result.professional_summary
