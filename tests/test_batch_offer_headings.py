"""Strict headings terminate inherited stack/preference categories."""
import pytest

from app.services.job_sections import MANDATORY, extract_sections


@pytest.mark.parametrize('heading', [
    'Required Qualifications', 'Required Skills and Experience',
    'Requirements Qualifications & Experience', 'Skills and attributes for success',
    'To qualify for the role, you must have', 'What we look for',
    'We are looking for', 'We are looking for you, if you have',
    'We are looking for, you, if you have',
])
@pytest.mark.parametrize('colon', ['', ':'])
def test_mandatory_headings_terminate_stack(heading, colon):
    units, headings = extract_sections(f'Tech Stack\nPython\n{heading}{colon}\nKnowledge of Linux')
    assert heading in headings
    assert {u.quote: u.category for u in units} == {
        'Python': 'competency', 'Knowledge of Linux': 'mandatory',
    }


@pytest.mark.parametrize('apostrophe', ["'", '’'])
@pytest.mark.parametrize('colon', ['', ':'])
def test_marketing_heading_terminates_preference(apostrophe, colon):
    heading = f'Here{apostrophe}s why you{apostrophe}ll love Example Systems'
    units, headings = extract_sections(
        f'Nice to Have\nExperience with Rust\n{heading}{colon}\nAnnual learning allowance')
    assert heading in headings
    assert {u.quote: u.category for u in units} == {
        'Experience with Rust': 'preferred', 'Annual learning allowance': 'benefits',
    }


def test_required_qualifications_sentence_is_not_a_heading():
    text = 'Required qualifications include Python and SQL.'
    assert not MANDATORY.fullmatch(text)
    _, headings = extract_sections(text)
    assert text not in headings


def test_stack_required_preferred_and_services_keep_exact_quotes():
    units, _ = extract_sections('Tech Stack:\nPython\nRequired Qualifications:\n'
        'Proven experience delivering AI systems.\nNice to Have:\nExperience with Rust.\n'
        'Scope of Services:\nDesign AI solutions.')
    assert {u.quote: u.category for u in units} == {
        'Python': 'competency',
        'Proven experience delivering AI systems.': 'mandatory',
        'Experience with Rust.': 'preferred',
        'Design AI solutions.': 'responsibility',
    }
