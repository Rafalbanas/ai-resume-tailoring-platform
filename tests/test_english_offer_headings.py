"""Literal English headings preserve qualification and employer-offer boundaries."""
import pytest

from app.services.job_sections import extract_sections


@pytest.mark.parametrize('apostrophe', ["'", '’'])
@pytest.mark.parametrize('comma', ['', ','])
@pytest.mark.parametrize('colon', ['', ':'])
def test_english_headings_mapping_and_exact_quotes(apostrophe, comma, colon):
    heading = f'You{apostrophe}re a perfect match for the role{comma} if{colon}'
    text = ('Responsibilities:\nDesigning workflows\nPython\n' + heading
            + '\nWorking knowledge of Java\nIt would be an additional advantage if you:'
            + '\nExperience in AWS\nWhy is joining us worth it?\nFree training/membership')
    units, _ = extract_sections(text)
    assert {unit.quote: unit.category for unit in units} == {
        'Designing workflows': 'responsibility',
        'Python': 'responsibility',
        'Working knowledge of Java': 'mandatory',
        'Experience in AWS': 'preferred',
        'Free training/membership': 'benefits',
    }


@pytest.mark.parametrize('valuable', ['', 'valuable '])
@pytest.mark.parametrize('examples', ['', ', such as'])
@pytest.mark.parametrize('colon', ['', ':'])
def test_nested_benefit_heading_preserves_context(valuable, examples, colon):
    heading = f'We offer {valuable}benefits{examples}{colon}'
    text = ('Why is joining us worth it?\nYou can work remotely\n' + heading
            + '\nthe sports membership card,\nmany more')
    units, _ = extract_sections(text)
    assert {unit.quote: unit.category for unit in units} == {
        'You can work remotely': 'benefits',
        'the sports membership card,': 'benefits',
        'many more': 'benefits',
    }
