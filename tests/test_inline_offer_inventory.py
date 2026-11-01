"""
Test suite for inline offer inventory handling.
Ensures that `normalize_source_layout` and `AnalysisInventory.build` correctly
partition synthetic mixed-content strings into separate passages with correct hints.
"""

from app.models.job import JobRequest
from app.services.job_sections import extract_sections
from app.services.ollama_analysis import AnalysisInventory


def test_inventory_build_partitioning(profile):
    job_description = (
        "Opis firmy. Idealnie abyś posiadał/a: • Znajomość SQL. • Doświadczenie w obsłudze aplikacji. "
        "Mile widziane: • Wiedza z zakresu ciągłości działania. Ze swej strony możemy zaoferować: • Owoce."
    )
    job = JobRequest(
        company="Synthetic",
        role="Support",
        job_description=job_description,
        tailoring_level=0.0,
        workflow="job",
        cv_name="test_cv",
        source_cv="test_cv"
    )

    inventory = AnalysisInventory.build(job, profile)

    # Requirement: source_text must remain identical to the original input.
    assert inventory.source_text == job.job_description

    # Requirements: Verify separate passages for SQL, Experience (mandatory hints) and Knowledge (preferred hint).
    # The passages are built by iterating over lines of raw text (after normalization).
    # Because of normalize_source_layout, we expect specific identifiable lines.

    # Check hints for SQL
    sql_passage = next((p for p in inventory.passages.values() if p["text"] == "Znajomość SQL."), None)
    assert sql_passage is not None
    assert "mandatory" in sql_passage["hints"]

    # Check hints for Experience
    exp_passage = next((p for p in inventory.passages.values() if p["text"] == "Doświadczenie w obsłudze aplikacji."), None)
    assert exp_passage is not None
    assert "mandatory" in exp_passage["hints"]

    # Check hints for Knowledge (preferred)
    knowledge_passage = next((p for p in inventory.passages.values() if p["text"] == "Wiedza z zakresu ciągłości działania."), None)
    assert knowledge_passage is not None
    assert "preferred" in knowledge_passage["hints"]

def test_extract_sections_partitioning():
    raw_text = (
        "Opis firmy. Idealnie abyś posiadał/a: • Znajomość SQL. • Doświadczenie w obsłudze aplikacji. "
        "Mile widziane: • Wiedza z zakresu ciągłości działania. Ze swej strony możemy zaoferować: • Owoce."
    )

    units, _ = extract_sections(raw_text)

    # Verify SQL is mandatory
    sql_unit = next((u for u in units if "Znajomość SQL" in u.quote), None)
    assert sql_unit is not None
    assert sql_unit.category == "mandatory"

    # Verify Knowledge is preferred
    knowledge_unit = next((u for u in units if "Wiedza z zakresu ciągłości działania" in u.quote), None)
    assert knowledge_unit is not None
    assert knowledge_unit.category == "preferred"
