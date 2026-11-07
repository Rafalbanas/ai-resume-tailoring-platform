"""Tests for decoded headings and source normalization in job sections."""
import pytest

from app.services.job_sections import REQUIREMENT_SIGNAL, extract_sections


def test_standalone_star():
    """Test that '⭐ Mile widziane' acts as a switch to preferred even without colon."""
    text = "Wymagania\nPython\n⭐ Mile widziane\nDocker"
    units, _ = extract_sections(text)
    # Python should be mandatory (from 'Wymagania' heading match)
    assert any(u.name == "Python" and u.category == "mandatory" for u in units)
    # Docker should be preferred (from '⭐ Mile widziane' matching PREFERRED)
    assert any(u.name == "Docker" and u.category == "preferred" for u in units)


@pytest.mark.parametrize("heading", [
    "⭐ Mile widziane:",
    "✨ Mile widziane",
    "⭐️ Mile widziane",
])
def test_parameterized_mile_widziane(heading):
    """Test that both star and sparkly emojis are correctly normalized as preferred headings."""
    text = f"Requirements:\nJava\n{heading}\nGo"
    units, _ = extract_sections(text)
    # Java mandatory, Go preferred
    assert any(u.name == "Java" and u.category == "mandatory" for u in units)
    assert any(u.name == "Go" and u.category == "preferred" for u in units)


def test_requirement_signal_polish():
    """Test that REQUIREMENT_SIGNAL identifies Polish terms for ability and knowledge."""
    assert REQUIREMENT_SIGNAL.search("Zdolność do pracy w zespole") is not None
    assert REQUIREMENT_SIGNAL.search("Podstawowa wiedza z zakresu Python") is not None


def test_reset_preferred_to_mandatory():
    """Test that 'Experience required' heading resets the category to mandatory."""
    text = "Preferred skills:\nPython (preferred)\nExperience required:\nEnglish proficiency\nC++"
    units, _ = extract_sections(text)
    # Requirement 'English proficiency' should be 'mandatory'
    # Requirement 'C++' should also be 'mandatory'
    mandatory_count = sum(1 for u in units if u.category == 'mandatory')
    assert mandatory_count >= 2
    # "Python (preferred)" is preferred
    assert units[0].category == 'preferred'


def test_protection_of_technical_symbols():
    """Ensure technical symbols like C++, C#, B2+, 3+ are not stripped and and source quotes are preserved."""
    text = "Requirements:\nC++ and C#\nLevel B2+ and 3+"
    units, _ = extract_sections(text)
    assert any("C++" in u.name for u in units)
    assert any("C#" in u.name for u in units)
    assert any("B2+" in u.name for u in units)
    assert any("3+" in u.name for u in units)


def test_source_quote_preservation():
    """Ensure that the original source quote is preserved in SourceUnit."""
    text = "Technical Skills:\nPython (preferred); Java proficiency"
    units, _ = extract_sections(text)
    # Check that the quote contains the original text
    assert any("Python (preferred); Java proficiency" in u.quote for u in units)
