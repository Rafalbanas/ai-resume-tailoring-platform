"""Regressions reconstructed from the October context audit (synthetic facts only)."""

from copy import deepcopy

import pytest
from jsonschema import Draft202012Validator

from app.models.job import JobRequest
from app.models.resume import TailoredResume
from app.services.job_sections import extract_sections
from app.services.ollama_analysis import AnalysisInventory, CompactAssessment, OllamaAnalysisError, plan_batches
from app.services.ollama_payload import compact_analysis, compact_generation
from app.services.ollama_schema import resume_schema
from app.services.ollama_tokens import QwenTokenCounter
from app.services.semantic_requirements import source_components


def test_polish_boundaries_and_optional_tenure():
    units, _ = extract_sections(
        "Czym się zajmiesz:\nAdministracja M365\nCzego oczekujemy:\nMinimum 2 lata wsparcia IT, najlepiej u wielu klientów.\nMile widziane:\nLinux\nOferujemy:\nBudżet szkoleniowy"
    )
    assert [u.category for u in units] == ["responsibility", "mandatory", "preferred", "benefits"]
    assert units[1].name == "Minimum 2 lata wsparcia IT"
    assert "najlepiej" in units[1].quote


def test_polish_practical_product_and_keeps_scope():
    parts, op = source_components("Praktycznej znajomości Exchange Online, Entra ID i Intune")
    assert op == "all"
    assert parts == ["Praktycznej znajomości " + p for p in ["Exchange Online", "Entra ID", "Intune"]]


def test_keyed_contract_covers_ids_and_separates_context(profile):
    job = JobRequest(
        company="Synthetic",
        role="IT",
        job_description="Tech stack\nIntune\nCzego oczekujemy:\nZnajomość PowerShell\nCzym się zajmiesz:\nObsługa klientów",
    )
    inv = AnalysisInventory.build(job, profile)
    ids = list(inv.passages)
    schema = inv.keyed_schema(ids)
    validator = Draft202012Validator(schema)
    rows = {}
    for pid, passage in inv.passages.items():
        if "mandatory" in passage["hints"]:
            rows[pid] = dict(
                k="requirement", n="PowerShell", priority="mandatory", s="missing", f=[], why="No evidence."
            )
        else:
            rows[pid] = dict(k="responsibility" if "responsibility" in passage["hints"] else "context")
    assert not list(validator.iter_errors({"assessments": rows}))
    broken = deepcopy(rows)
    del broken[ids[-1]]
    assert list(validator.iter_errors({"assessments": broken}))
    tag = next(pid for pid, p in inv.passages.items() if p["text"] == "Intune")
    broken = deepcopy(rows)
    broken[tag] = dict(k="requirement", n="Intune", priority="mandatory", s="strong", f=["F1"], why="Tag exists.")
    # Grammar leaves category interpretation to the model; factual validation
    # independently rejects unsupported product/priority claims.
    assert not list(validator.iter_errors({"assessments": broken}))
    qualification = next(pid for pid, p in inv.passages.items() if p["text"] == "Znajomość PowerShell")
    broken = deepcopy(rows)
    del broken[qualification]["why"]
    assert list(validator.iter_errors({"assessments": broken}))
    assert list(validator.iter_errors({"assessments": {pid: {"k": "context"} for pid in ids}}))
    with pytest.raises(OllamaAnalysisError):
        inv.validate_rows(
            [CompactAssessment(p=qualification, k="requirement", n="PowerShell", why="No evidence", f=["FAKE"])], ids
        )


def test_generation_compaction_removes_only_exact_duplicates():
    fact = dict(source_id="education:0", type="education", owner="College", fact="IT diploma", owner_index=0)
    sentinel = dict(fact, fact="Unduplicated fact")
    payload = dict(
        candidate_facts={"education": [fact, sentinel], "employment_history": [{"company": "Synthetic"}]},
        source_catalog=[fact],
        retrieval={"selected": ["education:0"]},
        eligible_skills=[dict(id="s1", name="Python", wording="Python basics", level="basic", evidence=["fact"])],
        analysis_summary={"key_requirements": ["IT diploma"], "requirements_with_evidence": [{"name": "IT diploma"}]},
        layout_guide={"max": 4},
        layout_constraints={"max": 4},
    )
    original = deepcopy(payload)
    wire = compact_generation(payload)
    assert payload == original
    assert wire["source_catalog"] == [fact]
    assert wire["candidate_facts"]["education"] == [sentinel]
    assert wire["candidate_facts"]["employment_history"] == payload["candidate_facts"]["employment_history"]
    assert "retrieval" not in wire and "key_requirements" not in wire["analysis_summary"]
    assert wire["eligible_skills"] == [dict(id="s1", name="Python", wording="Python basics", level="basic")]


def test_analysis_encoding_is_reversible():
    payload = dict(
        evidence={
            "F1": ["experience", "O1", "Same fact", "declaration"],
            "F2": ["project", "O2", "Same fact", "implemented_artifact"],
        },
        evidence_owners={
            "O1": dict(name="Employer", employment_index=0),
            "O2": dict(name="Project", employment_index=None),
        },
        employment_dates=[{"index": 0, "start": "2020"}],
        passages=[
            {
                "id": "P1",
                "text": "Entire text",
                "hints": [],
                "section": "",
                "requires_assessment": True,
                "context_only": False,
            }
        ],
    )
    original = deepcopy(payload)
    wire = compact_analysis(payload)
    assert payload == original
    assert {fid: row[:-1] + [wire["evidence_strengths"][row[-1]]] for fid, row in wire["evidence"].items()} == payload[
        "evidence"
    ]
    assert {
        oid: dict(zip(wire["evidence_owner_fields"], row, strict=True)) for oid, row in wire["evidence_owners"].items()
    } == payload["evidence_owners"]
    assert wire["passages"][0]["text"] == "Entire text"


def test_empty_collections_have_no_empty_enum_or_dangling_refs():
    schema = resume_schema(TailoredResume.model_json_schema(), [], [], [], [])
    Draft202012Validator.check_schema(schema)
    import json

    assert '"enum": []' not in json.dumps(schema)
    draft = dict(
        headline="",
        professional_summary="",
        summary_source_fact_ids=[],
        core_skills=[],
        selected_skill_ids=[],
        experience=[],
        education=[],
        projects=[],
    )
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(draft))
    for key in ["core_skills", "selected_skill_ids", "summary_source_fact_ids", "education", "projects", "experience"]:
        invalid = deepcopy(draft)
        invalid[key] = ["invented"]
        assert list(validator.iter_errors(invalid))


def test_employer_citations_and_required_education_summary():
    catalog = [
        dict(
            source_id=f"experience:{i}:fact:0", type="experience", owner=f"Employer {i}", owner_index=i, fact="Support"
        )
        for i in range(2)
    ]
    catalog += [
        dict(source_id=f"education:{i}", type="education", owner=f"College {i}", owner_index=i, fact="IT diploma")
        for i in range(3)
    ]
    history = [dict(company=f"Employer {i}", title="Support") for i in range(2)]
    schema = resume_schema(TailoredResume.model_json_schema(), catalog, [], [], history)
    Draft202012Validator.check_schema(schema)
    draft = dict(
        headline="Support",
        professional_summary="Support",
        summary_source_fact_ids=["experience:0:fact:0"],
        core_skills=[],
        selected_skill_ids=[],
        experience=[
            dict(
                company=f"Employer {i}",
                title="Support",
                dates="",
                bullets=[dict(text="Support", source_fact_ids=[f"experience:{i}:fact:0"])],
            )
            for i in range(2)
        ],
        education=[dict(institution=f"College {i}", source_fact_ids=[f"education:{i}"]) for i in range(3)],
        projects=[],
    )
    validator = Draft202012Validator(schema)
    assert not list(validator.iter_errors(draft))
    for modify in [
        lambda d: d.pop("summary_source_fact_ids"),
        lambda d: d.pop("education"),
        lambda d: d["education"].pop(),
        lambda d: d["experience"].pop(),
        lambda d: d["experience"][0]["bullets"][0].update(source_fact_ids=["experience:1:fact:0"]),
        lambda d: d["education"][0].update(source_fact_ids=["education:1"]),
    ]:
        invalid = deepcopy(draft)
        modify(invalid)
        assert list(validator.iter_errors(invalid))


def test_planner_uses_prompt_counter_not_schema_bytes(profile):
    inv = AnalysisInventory.build(
        JobRequest(company="Synthetic", role="IT", job_description="Requirements\nExperience with Python."), profile
    )
    calls = []

    def count(payload):
        calls.append(payload)
        return 9404

    assert plan_batches(inv, 6144, 16384, prompt_tokens=count) == [list(inv.passages)]
    assert len(calls[-1]["evidence"]) == len(inv.evidence)
    with pytest.raises(OllamaAnalysisError, match="exceed"):
        plan_batches(inv, 8192, 16384, prompt_tokens=count)


def test_unverified_tokenizer_is_refused(tmp_path):
    path = tmp_path / "tokenizer.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="Unverified"):
        QwenTokenCounter(path, "qwen3.5:9b")
    with pytest.raises(ValueError, match="not verified"):
        QwenTokenCounter(path, "unrelated-model")


def test_revalidation_of_verified_portal_tags_is_idempotent(profile):
    from app.models.job import JobAnalysis
    from app.services.analysis_validator import AnalysisValidator

    source = "Requirements\nExperience with Python.\nTech stack\nPython\nadvanced\nLinux\nbasic"
    draft = JobAnalysis(
        company="Synthetic",
        role="Support",
        strong_matches=[],
        partial_matches=[],
        missing_requirements=[],
        recommendation="REVIEW",
        match_level="LOW",
    )
    validator = AnalysisValidator(profile)
    first = validator.validate(draft, source)
    first.analysis_method = "llm_validated"
    second = validator.validate(first, source, semantic=True)
    third = validator.validate(second, source, semantic=True)
    assert second.is_reliable and third.is_reliable
    assert not second.classification_issues
    assert [(r.name, r.status) for r in second.role_competencies] == [
        (r.name, r.status) for r in third.role_competencies
    ]


def test_unrelated_fact_cannot_prove_defender_or_practical_entra(profile):
    from app.models.job import JobRequirement
    from app.services.analysis_validator import AnalysisValidator
    from tests.test_evidence_matching import candidate

    for scope in ["Defender for Endpoint knowledge", "Practical knowledge of Entra ID"]:
        draft = candidate()
        draft.requirements = [
            JobRequirement(
                name=scope,
                source_quote=scope,
                status="strong",
                source_fact_ids=["experience:0:fact:0"],
                reason="Unrelated Python fact",
            )
        ]
        result = AnalysisValidator(profile).validate(draft, "Requirements\n" + scope, semantic=True)
        assert result.requirements[0].status == "missing"
        assert not result.requirements[0].source_fact_ids
        assert result.evidence_issues and not result.is_reliable


def test_user_fact_conditions_preserved_without_hiding_analysis_evidence(profile):
    from app.services.cv_content_policy import cv_catalog

    fact = profile.experience[0].facts[0]
    profile.experience[0].cv_fact_conditions = {fact: ["SAP"]}
    serialized = profile.model_dump_json()
    assert type(profile).model_validate_json(serialized).experience[0].cv_fact_conditions == {fact: ["SAP"]}
    job = JobRequest(company="Synthetic", role="Support", job_description="Requirements\nSupport Windows users daily.")
    inv = AnalysisInventory.build(job, profile)
    assert any(e.text == fact for e in inv.evidence.values())
    assert not any(e.text == fact for e in cv_catalog(profile, job).prompt_entries)
    job.job_description += "\nSAP"
    assert any(e.text == fact for e in cv_catalog(profile, job).prompt_entries)


def test_employment_without_selected_facts_keeps_identity_without_invented_bullets():
    from app.services.ollama_schema import validate_resume_selections

    history = [dict(company="Synthetic", title="Support")]
    schema = resume_schema(TailoredResume.model_json_schema(), [], [], [], history)
    draft = dict(
        headline="Support",
        professional_summary="",
        summary_source_fact_ids=[],
        core_skills=[],
        selected_skill_ids=[],
        experience=[dict(company="Synthetic", title="Support", dates="", bullets=[])],
        education=[],
        projects=[],
    )
    assert not list(Draft202012Validator(schema).iter_errors(draft))
    validate_resume_selections(TailoredResume.model_validate(draft), [], history)
    draft["experience"][0]["bullets"] = [dict(text="Invented achievement", source_fact_ids=["fake"])]
    assert list(Draft202012Validator(schema).iter_errors(draft))


def test_runtime_rejects_duplicate_education_even_with_correct_array_length():
    from app.services.ollama_schema import validate_resume_selections

    catalog = [
        dict(source_id=f"education:{i}", type="education", owner=f"College {i}", owner_index=i, fact="Diploma")
        for i in range(2)
    ]
    draft = TailoredResume(
        headline="",
        professional_summary="",
        summary_source_fact_ids=["education:0"],
        core_skills=[],
        selected_skill_ids=[],
        experience=[],
        education=[dict(institution="College 0", source_fact_ids=["education:0"])] * 2,
        projects=[],
    )
    with pytest.raises(ValueError, match="exactly once"):
        validate_resume_selections(draft, catalog, [])


def test_it_support_tenure_counts_duties_and_excludes_titles():
    from app.models.candidate import CandidateProfile
    from app.services.evidence_matching import EvidenceMatcher
    from app.services.fact_catalog import FactCatalog

    profile = CandidateProfile.model_validate(
        dict(
            personal=dict(name="Synthetic"),
            experience=[
                dict(
                    company="Synthetic",
                    title="IT Support",
                    start="2023-01",
                    end="2025-12",
                    facts=["Resolved Windows incidents for internal users in IT support."],
                )
            ],
        )
    )
    match = EvidenceMatcher(FactCatalog(profile)).match("Minimum 2 years of IT support experience")
    assert match.status == "strong" and match.observed_years >= 2
    profile.experience[0].facts = ["Processed invoices using Comarch Optima."]
    match = EvidenceMatcher(FactCatalog(profile)).match("Minimum 2 years of IT support experience")
    assert match.status == "missing" and not match.entries


def test_missing_product_schema_has_standalone_enum_not_ignored_ref_sibling(profile):
    profile.skills["cloud"] = ["Entra ID"]
    job = JobRequest(
        company="Synthetic", role="Support", job_description="Czego oczekujemy:\nPraktycznej znajomości Entra ID"
    )
    inv = AnalysisInventory.build(job, profile)
    pid = next(pid for pid, p in inv.passages.items() if p["text"].startswith("Praktycznej"))
    schema = inv.keyed_schema([pid])
    ref = schema["properties"]["assessments"]["properties"][pid]["$ref"].split("/")[-1]
    row = schema["$defs"][ref]
    assert row["properties"]["s"] == {"type": "string", "enum": ["missing"]}
    draft = {
        "assessments": {
            pid: dict(
                k="requirement",
                n="Practical knowledge of Entra ID",
                priority="mandatory",
                s="partial",
                f=["F1"],
                why="Declared skill only.",
            )
        }
    }
    assert list(Draft202012Validator(schema).iter_errors(draft))
