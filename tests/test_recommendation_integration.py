"""Advice must reflect source-backed mandatory groups, not preferred matches."""

from app.models.candidate import CandidateProfile
from app.models.job import JobAnalysis
from app.services.analysis_validator import AnalysisValidator


def evaluate(lines):
    profile = CandidateProfile.model_validate({
        'personal': {'name': 'Synthetic Candidate'},
        'experience': [{'company': 'Example', 'title': 'Developer', 'start': '2024-01',
                        'facts': ['Developed Python automation scripts.']}],
    })
    candidate = JobAnalysis(company='Example', role='Engineer', strong_matches=[],
                            partial_matches=[], missing_requirements=[],
                            recommendation='APPLY', match_level='HIGH')
    return AnalysisValidator(profile).validate(candidate, '\n'.join(lines))


def test_majority_unconfirmed_mandatory_groups_require_review():
    result = evaluate(['Requirements', 'Python', 'Terraform', 'Amazon Bedrock', 'ClickHouse'])
    assert result.is_reliable
    assert result.scoring_counts['confirmed'] == 1
    assert result.scoring_counts['not_confirmed_or_gap'] == 3
    assert result.match_level == 'LOW'
    assert result.recommendation == 'REVIEW'
    assert 'missing evidence does not establish inability' in result.reasoning_summary


def test_preferred_and_duplicate_matches_do_not_rescue_mandatory_gaps():
    result = evaluate(['Requirements', 'Python', 'Python', 'Terraform', 'ClickHouse',
                       'Preferred qualifications', 'Python'])
    assert result.is_reliable
    assert result.scoring_counts['mandatory_groups'] == 3
    assert result.recommendation == 'REVIEW'


def test_fully_supported_mandatory_requirement_still_allows_apply():
    result = evaluate(['Requirements', 'Python'])
    assert result.is_reliable
    assert result.recommendation == 'APPLY'
