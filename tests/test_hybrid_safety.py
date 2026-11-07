from datetime import date

import pytest

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator
from app.services.evidence_matching import EvidenceMatcher


def candidate():
    return JobAnalysis(company='Example', role='Support', strong_matches=[], partial_matches=[],
                       missing_requirements=[], recommendation='REVIEW', match_level='LOW')

@pytest.fixture
def contextual_profile():
    return CandidateProfile.model_validate({
        'personal': {'name': 'Synthetic Candidate'},
        'skills': {'languages': ['English B2', 'Polish Native'], 'programming': ['Python']},
        'experience': [
            {'company': 'Example Operations', 'title': 'IT Specialist', 'start': 'Mar 2023', 'end': 'May 2024', 'facts': [
                'Provided L1 and L2 technical support to users.',
                'Used MS SQL Server and T-SQL for operational queries, troubleshooting and data verification.',
                'Investigated application and network incidents and analyzed logs to identify root causes.',
            ]},
        ],
        'projects': [{
            'name': 'Example API client',
            'technologies': ['Python', 'HTTPX', 'JSON', 'JavaScript'],
            'facts': [
                'Implemented REST API integration using Python, HTTPX and JSON for HTTP endpoints.',
                'Uses AI coding assistants and Codex for debugging, code analysis and workflow automation.',
                'Implemented client-side JavaScript using fetch for API requests.',
            ]
        }]
    })

def evaluate(text, profile):
    validator = AnalysisValidator(profile)
    validator.matcher = EvidenceMatcher(validator.catalog, as_of=date(2026, 10, 11))
    return validator.validate(candidate(), text)

def test_english_b2_does_not_prove_c1(contextual_profile):
    # Profile has English B2. Requirement is C1.
    # Current behavior: B2 does not satisfy C1.
    req = evaluate('Requirements\nEnglish C1', contextual_profile).requirements[0]
    assert req.status == 'partial'

def test_python_project_does_not_prove_two_years_employment(contextual_profile):
    # Profile has a Python project. Requirement is 2 years of Python employment.
    # Project experience should not count towards "years of experience" for employment requirements.
    req = evaluate('Requirements\n2 years of Python experience', contextual_profile).requirements[0]
    assert req.status == 'missing'

def test_python_or_kubernetes_strong(contextual_profile):
    # Requirement: Python OR Kubernetes. Profile has Python.
    # Should be strong.
    req = evaluate('Requirements\nPython OR Kubernetes', contextual_profile).requirements[0]
    assert req.status == 'strong'
    assert req.operator == 'any'

def test_python_and_kubernetes_partial(contextual_profile):
    result = evaluate('Requirements\nPython AND Kubernetes', contextual_profile)
    assert result.match_level == 'LOW'
    assert len(result.requirements) == 2
