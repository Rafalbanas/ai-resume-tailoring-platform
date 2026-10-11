"""Export regressions use synthetic contacts and attested candidate data only."""
import re
from pathlib import Path
from zipfile import ZipFile

import pytest
from docx import Document
from pypdf import PdfReader

from app.models.candidate import CandidateProfile
from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.docx_generator import generate_docx
from app.services.fact_catalog import FactCatalog
from app.services.fact_validator import FactValidator
from app.services.languages import profile_languages
from app.services.pdf_generator import PDFGenerator
from app.services.professional_summary import build_summary
from app.services.resume_export import contacts, prepare_resume, web_link
from tests.test_skills_bank import bank, skill


def text_key(text):
    return re.sub(r"\W+", "", text).casefold()


@pytest.mark.parametrize("layout", ["modern_sidebar", "ats_classic"])
def test_contacts_visible_extracted_and_clickable_in_both_formats(tmp_path, profile, resume_payload, layout):
    profile.personal.name = "Żaneta Łęcka"
    profile.personal.email = "zaneta@example.com"
    profile.personal.location = "Łódź, Poland"
    profile.personal.phone = "+48 123 456 789"
    profile.personal.github = "https://github.com/ExampleEngineer"
    profile.personal.linkedin = "https://www.linkedin.com/in/żaneta-łęcka/"
    profile.personal.website = "https://example.engineering"
    pdf = tmp_path / "resume.pdf"
    docx = tmp_path / "resume.docx"
    resume = TailoredResume.model_validate(resume_payload)
    PDFGenerator(Path("templates"), Path("static"), tmp_path).generate(resume, profile, pdf, template_name=layout)
    generate_docx(resume, profile, docx, template_name=layout)
    reader = PdfReader(pdf)
    text = text_key("\n".join(page.extract_text() for page in reader.pages))
    targets = {str(a.get_object().get("/A", {}).get("/URI", ""))
               for page in reader.pages for a in page.get("/Annots", [])}
    xml = ZipFile(docx).read("word/document.xml").decode()
    relationships = {r.target_ref for r in Document(docx).part.rels.values() if r.reltype.endswith("/hyperlink")}
    for contact in contacts(profile):
        assert text_key(contact.display) in text
        assert contact.display in xml
        if contact.target:
            assert contact.target in targets
            assert contact.target in relationships
    assert text_key(profile.personal.name) in text
    assert "Żaneta Łęcka" in xml
    assert "GDPR" in "\n".join(page.extract_text() for page in reader.pages)


@pytest.mark.parametrize("address", ["", "not-an-email", "user@", "user example.com"])
def test_invalid_email_blocks_export(tmp_path, profile, resume_payload, address):
    profile.personal.email = address
    r = TailoredResume.model_validate(resume_payload)
    with pytest.raises(ValueError, match="valid email"):
        PDFGenerator(Path("templates"), Path("static"), tmp_path).generate(r, profile, tmp_path / "bad.pdf")
    with pytest.raises(ValueError, match="valid email"):
        generate_docx(r, profile, tmp_path / "bad.docx")
    assert not (tmp_path / "bad.pdf").exists() and not (tmp_path / "bad.docx").exists()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "https://", "https://user:password@example.com", "https://bad host.com", "https://example.com:bad", "file:///tmp/secret"])
def test_invalid_link_blocks_export(url):
    with pytest.raises(ValueError):
        web_link(url)


def test_unicode_urls_are_encoded_once():
    url = web_link("https://linkedin.com/in/żaneta-łęcka/")
    assert "%C5%BC" in url
    assert web_link(url) == url


def test_languages_and_skill_labels_normalized_without_changing_source(profile, resume_payload):
    profile.skills["languages"] = ["English B2", "English - daily professional use", "Polish Native", "Hands-on Polish", "Polish Native"]
    r = TailoredResume.model_validate(resume_payload)
    r.core_skills = ["Hands-on Polish", "English B2 / daily professional use", "Hands-on Python", "Python", "Basic Docker", "Hands-on Tier 2 Support"]
    original = r.model_copy(deep=True)
    prepared = prepare_resume(r, profile)
    assert prepared.core_skills == ["Python", "Basic Docker", "Tier 2 Support"]
    assert profile_languages(profile) == ["English B2 — daily professional use", "Polish Native"]
    assert r == original


def test_verified_languages_never_selected_as_technical_skills(tmp_path, profile, resume_payload):
    profile.skills["languages"] = ["Polish Native", "English B2"]
    skills = [skill("Polish"), skill("English"), skill("Python")]
    store = bank(tmp_path, profile, skills)
    candidate = TailoredResume.model_validate(resume_payload)
    candidate.selected_skill_ids = [s.id for s in skills]
    result = FactValidator(profile, store).validate(candidate, JobRequest(company="Example", role="Support Engineer", job_description="Requirements\nPolish and English B2. Ability to read Python code."))
    assert result.resume.core_skills == ["Python"]
    assert result.resume.headline == "Support Engineer"


def test_sql_api_aliases_include_only_eligible_scoped_technologies(tmp_path, profile):
    skills = [skill("MS SQL", aliases=["SQL Server"]), skill("T-SQL"), skill("HTTPX"), skill("JSON"), skill("Python"), skill("TypeScript", verified=False), skill("JSON-LD"), skill("JWT Authentication"), skill("SQLite")]
    store = bank(tmp_path, profile, skills)
    selected = store.select_for_job([], "Technical Support: Working knowledge of SQL. REST API integration. Ability to read code.")
    names = {s.name for s in selected}
    assert {"MS SQL", "T-SQL", "HTTPX", "JSON", "Python"} <= names
    assert not {"TypeScript", "JSON-LD", "JWT Authentication", "SQLite"} & names


def test_summary_balances_employment_sql_api_language_and_projects():
    p = CandidateProfile.model_validate({
        "personal": {"name": "Candidate", "email": "candidate@example.com"},
        "summary_facts": ["Provides Tier 2 support for Example Telecom partners.", "Experienced in application and network troubleshooting.", "Analyzes application logs to identify root causes.", "Uses English at B2 level in daily professional work.", "Automates selected operational tasks with Python."],
        "experience": [{"company": "Example Telecom", "title": "Support Engineer (Tier 2)", "start": "2024-01", "end": "Present", "facts": ["Provided L1 and L2 support.", "Used SQL and T-SQL queries for troubleshooting and data verification."]}],
        "projects": [{"name": "Integration project", "facts": ["Integrates REST API HTTP endpoints using Python, HTTPX and JSON."]}]})
    catalog = FactCatalog(p)
    text, ids = build_summary(catalog, "Technical Support Engineer\nSQL, REST API debugging and communication")
    assert len(re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)) == 4
    assert len(text) <= 700
    for token in ["Example Telecom", "L1 and L2", "logs", "SQL", "HTTPX", "B2"]:
        assert token in text
    assert all(catalog.get(i) for i in ids)
    assert "API debugging" not in text and "B2+" not in text


def test_long_contacts_wrap_inside_sidebar(tmp_path, profile, resume_payload):
    profile.personal.email = "a" * 60 + "@example.com"
    profile.personal.github = "https://github.com/" + "long-profile-name-" * 8
    path = tmp_path / "long.pdf"
    PDFGenerator(Path("templates"), Path("static"), tmp_path).generate(TailoredResume.model_validate(resume_payload), profile, path)
    text = text_key("".join(p.extract_text() for p in PdfReader(path).pages))
    assert text_key(profile.personal.email) in text
    assert text_key(contacts(profile)[-1].display) in text


def test_export_omits_empty_sections(profile, resume_payload):
    r = TailoredResume.model_validate(resume_payload)
    r.projects = []
    r.certifications = []
    r.core_skills = ["", "English"]
    html = PDFGenerator(Path("templates"), Path("static")).render_html(r, profile)
    for heading in ["<h2>Skills</h2>", "<h2>Projects</h2>", "<h2>Certifications</h2>"]:
        assert heading not in html


def test_sidebar_overflow_never_silently_drops_final_sections(tmp_path, profile, resume_payload):
    r = TailoredResume.model_validate(resume_payload)
    r.core_skills = [f"Verified technology {i}: operational integration and troubleshooting" for i in range(18)]
    r.interests = ["Cycling", "Coffee"]
    profile.skills["languages"] = ["English B2", "Polish Native", "German A2"]
    output = tmp_path / "overflow.pdf"
    PDFGenerator(Path("templates"), Path("static"), tmp_path).generate(r, profile, output)
    text = text_key("".join(page.extract_text() for page in PdfReader(output).pages))
    for value in r.core_skills + r.interests + profile_languages(profile):
        assert text_key(value) in text
    assert PdfReader(output).trailer["/Root"].get("/StructTreeRoot") is not None


def test_languages_handle_reverse_native_and_programming_category(profile):
    profile.skills["languages"] = ["Native Polish", "English B2", "Python", "English B2+"]
    assert profile_languages(profile) == ["Polish Native", "English B2+"]


def test_truth_boundary_rejects_administration_from_basic_use(tmp_path, profile, resume_payload):
    profile.experience[0].facts = ["Used Docker for local testing and contacted the external firewall vendor."]
    store = bank(tmp_path, profile, [skill("Docker", level="basic")])
    r = TailoredResume.model_validate(resume_payload)
    r.experience[0].bullets[0].text = "Administered production Docker clusters and independently managed firewall infrastructure."
    result = FactValidator(profile, store).validate(r, JobRequest(company="Example", role="Support Engineer", job_description="Requirements\nDocker support for local testing."))
    assert result.resume.experience[0].bullets[0].text == profile.experience[0].facts[0]
    assert "Basic Docker" in result.resume.core_skills
    assert result.resume.experience[0].dates == "2022 – Present"


def test_confirmed_but_omitted_sql_creates_review_without_adding_it(profile, resume_payload):
    profile.experience[0].facts.append("Used SQL Server and T-SQL queries for operational troubleshooting.")
    r = TailoredResume.model_validate(resume_payload)
    r.professional_summary = "Automated a verified operational workflow with Python."
    r.core_skills = ["Python"]
    r.experience[0].bullets[0].text = profile.experience[0].facts[0]
    job = JobRequest(company="Example", role="Support Engineer", job_description="Requirements\nWorking knowledge of SQL for investigation and validation.\nEnglish B2+.")
    before = r.model_copy(deep=True)
    warnings = FactValidator(profile)._coverage_warnings(r, job)
    assert any("SQL" in w for w in warnings)
    assert not any("B2+" in w for w in warnings)
    assert r == before


def test_assisted_vendor_troubleshooting_remains_limited_and_idempotent(profile, resume_payload):
    profile.experience[0].facts = ["Supported Vendor Firewall troubleshooting."]
    r = TailoredResume.model_validate(resume_payload)
    r.experience[0].bullets[0].text = "Administered Vendor Firewall production systems."
    job = JobRequest(company="Example", role="Support Engineer", job_description="Requirements\nInvestigate technical support incidents.")
    validator = FactValidator(profile)
    result = validator.validate(r, job).resume
    assert result.experience[0].bullets[0].text == "Assisted with Vendor Firewall troubleshooting."
    assert validator.validate(result, job).resume == result


def test_encoded_url_separators_are_not_changed():
    url = "https://example.com/profile%2Fname?redirect=a%26b#part%20two"
    assert web_link(url) == url


def test_docx_does_not_stretch_rectangular_photo(tmp_path, profile, resume_payload):
    from PIL import Image
    photo = tmp_path / 'portrait.png'
    Image.new('RGB', (300, 150), 'navy').save(photo)
    output = tmp_path / 'photo.docx'
    generate_docx(TailoredResume.model_validate(resume_payload), profile, output, photo_enabled=True, photo_path=photo)
    image = Document(output).inline_shapes[0]
    assert image.width / image.height == pytest.approx(2.0)
