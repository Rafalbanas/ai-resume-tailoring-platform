"""Rich, scoped CVs from fictional evidence; no live model or private profile."""
from pathlib import Path

import pytest
from docx import Document
from pypdf import PdfReader

from app.models.job import JobAnalysis, JobRequest
from app.services.content_quality import project_sentences
from app.services.docx_generator import generate_docx
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.pdf_generator import PDFGenerator
from app.services.resume_export import validate_layout
from scripts.compare_resume_richness import OFFERS, rich_profile, sparse_draft


def checked(role, level=0):
    profile = rich_profile()
    job = JobRequest(company="Fictional", role=role, job_description="Requirements\n" + OFFERS[role],
                     tailoring_level=level)
    analysis = JobAnalysis(company=job.company, role=role, strong_matches=[], partial_matches=[],
                           missing_requirements=[], recommendation="REVIEW", match_level="LOW")
    validator = FactValidator(profile, analysis=analysis, review_key="synthetic-test-key")
    return profile, job, validator, validator.validate(sparse_draft(profile), job).resume


@pytest.mark.parametrize("role", OFFERS)
def test_sparse_draft_recovers_distinct_verified_details(role):
    profile, job, validator, resume = checked(role)
    assert 3 <= len(project_sentences(resume.professional_summary)) <= 5
    assert len(resume.professional_summary) > 200
    assert len(resume.experience[0].bullets) >= 2
    assert [e.title for e in resume.experience] == [e.title for e in profile.experience]
    assert [e.company for e in resume.experience] == [e.company for e in profile.experience]
    assert role not in resume.headline or role in profile.experience[0].title
    for experience in resume.experience:
        for bullet in experience.bullets:
            assert len(set(bullet.source_fact_ids)) == len(bullet.source_fact_ids)
            entries = validator.catalog.valid(bullet.source_fact_ids, kind="experience")
            assert entries
            assert all(profile.experience[e.owner_index].company == experience.company for e in entries)
    for project in resume.projects:
        entries = validator.catalog.valid(project.source_fact_ids, kind="project")
        assert entries and all(e.owner_name == project.name for e in entries)
        source_text = " ".join(e.text for e in entries)
        # Chosen paragraphs consist of whole attested sentences, not invented
        # technologies, results or metrics.
        assert all(sentence in source_text for sentence in project_sentences(project.description))
    again = validator.validate(resume, job).resume
    assert again == resume


def test_ml_transition_exposes_capabilities_without_renaming_employment():
    profile, _, _, resume = checked("ML Engineer")
    assert "Machine Learning" in resume.headline
    assert "Technical Support Engineer (L2)" in resume.headline
    assert resume.projects[0].name == "Academic ML thesis"
    assert resume.section_order.index("projects") < resume.section_order.index("experience")
    assert resume.section_order.index("education") < resume.section_order.index("experience")
    project = resume.projects[0]
    assert len(project_sentences(project.description)) >= 3
    combined = resume.professional_summary + " " + project.description
    for term in ("academic", "pandas", "scikit-learn", "cross-validation", "mean absolute error"):
        assert term in combined
    assert "commercial ML" not in combined
    _, _, _, support = checked("Technical Support Engineer")
    assert len(project.description) > len(next(p for p in support.projects if p.name == project.name).description)
    assert support.section_order.index("experience") < support.section_order.index("projects")
    assert support.headline == profile.experience[0].title


def test_devops_prioritizes_operations_lab_not_ml_keyword_density():
    _, _, _, resume = checked("DevOps Engineer")
    assert resume.projects[0].name == "Personal operations lab"
    assert "personal" in resume.projects[0].description.lower()
    assert "Kubernetes" not in resume.model_dump_json()
    assert "Terraform" not in resume.model_dump_json()
    assert "DevOps Engineer" not in resume.headline


@pytest.mark.parametrize("role", OFFERS)
def test_slider_changes_presentation_without_changing_facts(role):
    profile, _, _, target = checked(role, 0)
    _, _, _, middle = checked(role, 0.5)
    _, _, _, original = checked(role, 1)
    assert target.professional_summary != original.professional_summary
    assert original.headline == profile.experience[0].title
    assert original.section_order.index("experience") < original.section_order.index("projects")
    assert original.core_skills == [s for values in profile.skills.values() for s in values][:10]
    assert [e.company for e in target.experience] == [e.company for e in original.experience]
    assert sum(len(e.bullets) for e in target.experience) <= sum(len(e.bullets) for e in middle.experience)
    assert sum(len(e.bullets) for e in middle.experience) <= sum(len(e.bullets) for e in original.experience)


@pytest.mark.parametrize("role", OFFERS)
@pytest.mark.parametrize("template", ["ats_classic", "modern_sidebar"])
def test_full_content_survives_real_a4_exports(tmp_path, role, template):
    profile, job, validator, resume = checked(role)
    generator = PDFGenerator(Path("templates"), Path("static"), tmp_path)
    fitted, _ = generator.fit_resume(resume, profile, template_name=template,
                                    fact_validator=validator, job_text=job.relevance_text)
    assert fitted == resume
    html = generator.render_html(fitted, profile, template_name=template)
    document = generator._render_document(html)
    validate_layout(document)
    assert 1 <= len(document.pages) <= 2
    pdf, docx = tmp_path / "resume.pdf", tmp_path / "resume.docx"
    generator.generate(fitted, profile, pdf, template_name=template)
    generate_docx(fitted, profile, docx, template_name=template)
    for text in (" ".join(p.extract_text() for p in PdfReader(pdf).pages),
                 " ".join(p.text for p in Document(docx).paragraphs)):
        # PDF extraction may insert typographical ligatures/line wrapping.
        assert "Example Services" in text
        assert "Academic ML thesis" in text and "Personal operations lab" in text
        assert len(text.split()) >= 200
    assert html.index("Projects</h2>") < html.index("Experience</h2>") if (
        resume.section_order.index("projects") < resume.section_order.index("experience")) else (
        html.index("Experience</h2>") < html.index("Projects</h2>"))


def test_sparse_profile_is_not_padded(profile):
    profile.projects = []
    profile.education = []
    draft = sparse_draft(profile)
    job = JobRequest(company="Fictional", role="ML Engineer", job_description="Requirements\nPython machine learning.")
    resume = FactValidator(profile).validate(draft, job).resume
    assert resume.projects == []
    assert len(resume.experience[0].bullets) == 1
    assert "Machine Learning" not in resume.headline
    assert len(project_sentences(resume.professional_summary)) <= 3


@pytest.mark.parametrize("preserve_skills", [False, True])
def test_valid_semantic_approval_preserves_short_summary_and_owner_confirmation(preserve_skills):
    from app.services.summary_confirmation import summary_review
    from app.services.summary_review import sign_summary, valid_summary_attestation

    profile, job, validator, _ = checked("ML Engineer")
    draft = sparse_draft(profile)
    draft.professional_summary = ("Supports business customers. "
                                  "Automates repetitive diagnostic checks using Python.")
    draft.summary_source_fact_ids = [e.source_id for e in validator.catalog.prompt_entries
                                     if e.kind in {"summary", "experience"}
                                     and e.text in {
                                         "Provides technical support for business customers.",
                                         "Automates repetitive diagnostic checks using Python."}]
    draft.summary_attestation = sign_summary(draft, profile, validator.review_key)
    result = validator.validate(draft, job, preserve_skills=preserve_skills).resume
    assert result.professional_summary == draft.professional_summary
    assert valid_summary_attestation(result, profile, validator.review_key)
    assert summary_review(result, profile, validator.review_key, "draft:synthetic")["required"]


def test_changed_semantic_signature_cannot_preserve_unsupported_summary():
    from app.services.summary_review import sign_summary, valid_source_summary, valid_summary_attestation

    profile, job, validator, _ = checked("ML Engineer")
    draft = sparse_draft(profile)
    draft.summary_attestation = sign_summary(draft, profile, validator.review_key)
    draft.professional_summary = "Has ten years of commercial Kubernetes expertise."
    assert not valid_summary_attestation(draft, profile, validator.review_key)
    result = validator.validate(draft, job).resume
    assert result.professional_summary != draft.professional_summary
    assert valid_source_summary(result, profile, validator.review_key)
    assert not valid_summary_attestation(result, profile, validator.review_key)


async def test_sparse_new_draft_is_expanded_before_semantic_approval():
    from app.services.summary_review import review_summary, valid_source_summary, valid_summary_attestation

    profile, job, validator, _ = checked("ML Engineer")
    draft = sparse_draft(profile)
    draft.professional_summary = "Provides technical support and automates diagnostic checks with Python."
    draft.summary_source_fact_ids = [
        e.source_id for e in validator.catalog.prompt_entries if e.kind == "experience"
    ][:2]
    draft.summary_attestation = "model-supplied-signature"

    class Reviewer:
        async def _chat(self, *args, **kwargs):
            pytest.fail("Sparse rich-profile draft must not receive semantic approval")

    reviewed = await review_summary(Reviewer(), draft, profile)
    assert not reviewed.summary_attestation
    result = validator.validate(reviewed, job).resume
    assert 3 <= len(project_sentences(result.professional_summary)) <= 5
    assert valid_source_summary(result, profile, validator.review_key)
    assert not valid_summary_attestation(result, profile, validator.review_key)


def test_project_citations_do_not_claim_hidden_facts():
    _, _, validator, resume = checked("Technical Support Engineer")
    project = next(p for p in resume.projects if p.name == "Academic ML thesis")
    source = FactCatalog(validator.profile)
    assert all(source.get(i).text in project.description for i in project.source_fact_ids)
    assert not any("cross-validation" in source.get(i).text for i in project.source_fact_ids)


def test_education_metadata_is_retrievable_without_becoming_employment():
    profile = rich_profile()
    profile.education[0].thesis_summary = "Academic regression evaluation using held-out sensor measurements."
    catalog = FactCatalog(profile)
    entries = [e for e in catalog.prompt_entries if e.kind == "education"]
    assert any(e.text == "Specialisation: Machine Learning" for e in entries)
    assert any(e.text == profile.education[0].thesis_summary for e in entries)
    assert all(e.owner_index == 0 and e.owner_name == "Example University" for e in entries)


def test_reviewed_manual_content_is_not_expanded_or_reordered():
    _, job, validator, generated = checked("ML Engineer")
    manual = generated.model_copy(deep=True)
    manual.experience[0].bullets = manual.experience[0].bullets[:1]
    manual.section_order = ["summary", "experience", "projects", "education", "skills"]
    manual.projects[0].description = validator.profile.projects[0].facts[0]
    manual.projects[0].source_fact_ids = [
        e.source_id for e in validator.catalog.prompt_entries
        if e.kind == "project" and e.text == manual.projects[0].description]
    result = validator.validate(manual, job, preserve_skills=True).resume
    assert len(result.experience[0].bullets) == 1
    assert result.section_order == manual.section_order
    assert result.projects[0].description == manual.projects[0].description


def test_slider_reorders_verified_bank_but_cannot_unlock_learning(tmp_path):
    from app.models.skills import SkillEvidence, SkillsDocument, VerifiedSkill
    from app.services.skills_bank import SkillsBank

    profile = rich_profile()
    names = ["Windows", "Linux", "Docker", "Python", "SQL", "Bash", "Machine Learning"]
    skills = [VerifiedSkill(id=f"skill_test_{i}", name=name, category="Tools",
        level="basic" if name == "Machine Learning" else "hands_on", verified=True, allowed_in_cv=True,
        evidence=[SkillEvidence(source_type="manual_verified", source_id=f"manual:synthetic:{i}",
                                description=f"Attested use of {name}.")]) for i, name in enumerate(names)]
    skills.append(VerifiedSkill(id="skill_learning_kubernetes", name="Kubernetes", category="Tools",
                                level="learning"))
    path = tmp_path / "skills.json"
    path.write_text(SkillsDocument(skills=skills).model_dump_json())
    bank = SkillsBank(path, profile)
    outputs = []
    for level in (0, 0.5, 1):
        job = JobRequest(company="Synthetic", role="ML Engineer",
                         job_description="Requirements\nPython machine learning and Kubernetes.", tailoring_level=level)
        resume = FactValidator(profile, bank).validate(sparse_draft(profile), job).resume
        assert "Kubernetes" not in resume.core_skills
        assert "Kubernetes" not in resume.headline
        assert "Machine Learning" not in resume.core_skills  # Do not drop Basic.
        outputs.append(resume)
    assert outputs[0].core_skills[0] == "Basic Machine Learning"
    assert outputs[-1].core_skills[0] == "Windows"
    assert "Basic Machine Learning" in outputs[0].headline
